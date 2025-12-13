import * as http from "node:http";
import {ChildProcess, spawn} from "node:child_process";

import {
  createClient,
  AccessError,
  UnknownDatabaseError,
  Event as GelEvent,
} from "@dbsof/platform/gel";

import {schemaScript} from "@dbsof/studio/tabs/dashboard/exampleSchema.mts";

class Event extends (GelEvent as any) {}

const STARTUP_TIMEOUT = 5 * 60_000;

const sleep = (ms: number) =>
  new Promise<void>((resolve) =>
    setTimeout(() => {
      resolve();
    }, ms)
  );

function checkBackendAlive() {
  return new Promise<boolean>((resolve) => {
    const req = http.get(
      "http://localhost:5656/server/status/alive",
      (res) => {
        if (res.statusCode === 200) {
          resolve(true);
        } else {
          resolve(false);
        }
      }
    );
    req.on("error", () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function waitUntilAlive(
  check: () => Promise<boolean>,
  errMessage: string,
  event?: Event
) {
  for (let i = 0; i < STARTUP_TIMEOUT / 1000; i++) {
    if (await check()) {
      event?.set();
      return;
    }
    await sleep(1000);
  }
  if (event) {
    event.setError(errMessage);
  } else {
    throw new Error(errMessage);
  }
}

async function checkUIServerAlive() {
  return new Promise<boolean>((resolve) => {
    const req = http.get("http://localhost:3002/ui", (res) => {
      if (res.statusCode === 200) {
        resolve(true);
      } else {
        resolve(false);
      }
    });
    req.on("error", () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function checkConfigApplied() {
  try {
    const res = await fetch("http://localhost:5656/server-info");
    if (res.ok) {
      const info = await res.json();
      if (info.instance_config.cors_allow_origins.length > 0) {
        return true;
      }
    }
    return false;
  } catch {
    return false;
  }
}

export default async function globalSetup() {
  console.log("\n");

  let gelServerProc: ChildProcess | null = null;
  const gelServerAlive = new Event();
  let usingExistingDevServer = false;

  if (await checkBackendAlive()) {
    console.log("Re-using backend server already running on 5656");
    usingExistingDevServer = true;
    gelServerAlive.set();
  } else {
    console.log("Starting backend server...");

    const srvcmd = process.env.BACKEND_SERVER_BIN ?? "edgedb-server";

    const args = process.env.CI
      ? [
          "--temp-dir",
          "--security=insecure_dev_mode",
          "--testmode",
          "--port=5656",
        ]
      : ["--devmode"];

    gelServerProc = spawn(srvcmd, args) as ChildProcess;
    gelServerProc.once("close", (code) => {
      if (!gelServerAlive.done) {
        gelServerAlive.setError(
          `Backend server failed to start with exit code: ${code}`
        );
      }
    });
    waitUntilAlive(
      checkBackendAlive,
      "Backend server startup timed out",
      gelServerAlive
    );
  }

  let uiServerProc: ChildProcess | null = null;
  const uiServerAlive = new Event();

  if (await checkUIServerAlive()) {
    console.log("Re-using UI server already running on 3002");
    uiServerAlive.set();
  } else {
    console.log("Starting UI server...");
    uiServerProc = spawn("yarn", ["dev"], {
      env: {...process.env, NODE_ENV: undefined},
    }) as ChildProcess;
    uiServerProc.once("close", (code) => {
      if (!uiServerAlive.done) {
        uiServerAlive.setError(
          `UI server failed to start with exit code: ${code}`
        );
      }
    });
    waitUntilAlive(
      checkUIServerAlive,
      "UI server startup timed out",
      uiServerAlive
    );
  }

  await Promise.all([
    uiServerAlive.wait().then(() => {
      if (uiServerProc) console.log("...UI server running");
    }),
    gelServerAlive.wait().then(() => {
      if (gelServerProc) console.log("...Backend server running");
    }),
  ]);

  console.log("Creating '_test' database...");
  const client = createClient({port: 5656, tlsSecurity: "insecure"});
  try {
    await client.execute("drop database _test");
  } catch (err) {
    if (!(err instanceof UnknownDatabaseError)) throw err;
  }
  await client.execute("create database _test");
  const testClient = createClient({
    port: 5656,
    tlsSecurity: "insecure",
    database: "_test",
  });
  for (let i = 0; i < 10; i++) {
    await sleep(500);

    try {
      await testClient.execute(schemaScript);
      if (!usingExistingDevServer) {
        await testClient.execute(
          `configure instance set cors_allow_origins := {'*'}`
        );
        await waitUntilAlive(checkConfigApplied, "Config apply timed out");
      }
      break;
    } catch (err) {
      if (!(err instanceof AccessError)) {
        throw err;
      }
    }
  }
  console.log("... Done");

  globalThis.uiServerProc = uiServerProc;
  globalThis.gelServerProc = gelServerProc;

  console.log("\n");
}
