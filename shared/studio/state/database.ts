import {createContext, useContext} from "react";

import {action, observable, reaction, runInAction, when} from "mobx";
import {
  AnyModel,
  createContext as createMobxContext,
  getTypeInfo,
  idProp,
  Model,
  model,
  ModelClass,
  modelFlow,
  ModelTypeInfo,
  ObjectMap,
  prop,
  _async,
  _await,
  modelAction,
} from "mobx-keystone";

import {
  RawIntrospectionResult,
  getIntrospectionQuery,
} from "@dbsof/common/schemaData/queries";
import {
  buildTypesGraph,
  SchemaType,
  SchemaObjectType,
  SchemaScalarType,
  SchemaFunction,
  SchemaConstraint,
  SchemaPointer,
  SchemaAbstractAnnotation,
  SchemaExtension,
  SchemaAlias,
  SchemaGlobal,
  SchemaOperator,
} from "@dbsof/common/schemaData";
import {SchemaVersion} from "@dbsof/common/schemaData/utils";

import {fetchSchemaData, storeSchemaData} from "../idbStore";

import {instanceCtx} from "./instance";
import {Capabilities, connCtx, Connection} from "./connection";
import {SessionState, sessionStateCtx} from "./sessionState";
import {AuthenticationError, mockMode} from "@dbsof/platform/client";

export const dbCtx = createMobxContext<DatabaseState>();

const SCHEMA_DATA_VERSION = 8;

export interface StoredSchemaData {
  version: number;
  schemaId: string | null;
  schemaLastMigration: string | null | undefined;
  data: RawIntrospectionResult;
}

export interface SchemaData {
  objects: Map<string, SchemaObjectType>;
  objectsByName: Map<string, SchemaObjectType>;
  functions: Map<string, SchemaFunction>;
  operators: Map<string, SchemaOperator>;
  constraints: Map<string, SchemaConstraint>;
  scalars: Map<string, SchemaScalarType>;
  types: Map<string, SchemaType>;
  pointers: Map<string, SchemaPointer>;
  aliases: Map<string, SchemaAlias>;
  globals: Map<string, SchemaGlobal>;
  annotations: Map<string, SchemaAbstractAnnotation>;
  extensions: SchemaExtension[];
  shortNamesByModule: Map<string, Set<string>>;
}

@model("DatabaseState")
export class DatabaseState extends Model({
  $modelId: idProp,
  name: prop<string>(),

  sessionState: prop(() => new SessionState({})),
  tabStates: prop<ObjectMap<AnyModel>>(),
}) {
  @observable.ref
  connection: Connection | null = null;

  @observable
  branchAccessDisallowed = false;

  @action
  _setConnection(conn: Connection) {
    this.connection = conn;
  }

  _getTabState(modelType: string, stateClass: ModelClass<AnyModel>) {
    if (!this.tabStates.has(modelType)) {
      this._initTabState(stateClass);
    }
    return this.tabStates.get(modelType)!;
  }

  @modelAction
  private _initTabState(stateClass: ModelClass<AnyModel>) {
    const state = new stateClass({});
    this.tabStates.set(state.$modelType, state);
  }

  @observable
  loadingTabs = new Map<string, boolean>();

  @action
  setLoadingTab(stateClass: ModelClass<any>, loading: boolean) {
    this.loadingTabs.set(
      (getTypeInfo(stateClass) as ModelTypeInfo).modelType,
      loading
    );
  }

  refreshCaches(capabilities: number, statuses: string[]) {
    if (capabilities & Capabilities.DDL) {
      if (
        statuses.includes("CREATE DATABASE") ||
        statuses.includes("DROP DATABASE") ||
        statuses.includes("CREATE BRANCH") ||
        statuses.includes("DROP BRANCH") ||
        statuses.includes("ALTER BRANCH")
      ) {
        instanceCtx.get(this)!.fetchDatabaseInfo();
      } else {
        const dbState = dbCtx.get(this)!;
        dbState.fetchSchemaData();
      }
    }
  }

  @observable
  schemaId: string | null = null;
  @observable
  schemaLastMigration: string | null = null;
  @observable.ref
  schemaData: SchemaData | null = null;
  @observable
  fetchingSchemaData = false;

  @observable
  objectCount: number | null = null;

  onInit() {
    dbCtx.set(this, this);
    sessionStateCtx.set(this, this.sessionState);
    connCtx.setComputed(this, () => this.connection!);
  }

  onAttachedToRootStore() {
    const instanceState = instanceCtx.get(this)!;

    const fetchSchemaDisposer = when(
      () => this.connection !== null,
      () => this.fetchSchemaData()
    );

    const connectionDisposer = reaction(
      () => instanceState.currentRole,
      (currentRole) => {
        if (currentRole) {
          this._setConnection(
            instanceState.getConnection(this.name, this.sessionState)
          );
        }
      },
      {fireImmediately: true}
    );

    return () => {
      fetchSchemaDisposer();
      connectionDisposer();
    };
  }

  watchForSchemaChanges() {
    let fetchingDbInfo: Promise<void> | null = null;
    const listener = async () => {
      if (window.document.visibilityState === "visible") {
        const instanceState = instanceCtx.get(this);
        if (!instanceState || !this.schemaId || fetchingDbInfo !== null)
          return;

        fetchingDbInfo = instanceState.fetchDatabaseInfo();
        await fetchingDbInfo;
        fetchingDbInfo = null;

        const dbInfo = instanceState.databases?.find(
          (db) => db.name === this.name
        );

        if (dbInfo && dbInfo.last_migration != this.schemaLastMigration) {
          this.fetchSchemaData();
        }
      }
    };

    listener();

    window.addEventListener("visibilitychange", listener);
    window.addEventListener("focus", listener);

    return () => {
      window.removeEventListener("visibilitychange", listener);
      window.removeEventListener("focus", listener);
    };
  }

  updateObjectCount() {
    const abortController = new AbortController();
    this.connection
      ?.query(
        `select count(std::Object)`,
        undefined,
        {ignoreSessionConfig: true},
        abortController.signal
      )
      .then(({result}) => {
        if (result) {
          runInAction(() => {
            this.objectCount = Number(result[0]);
          });
        }
      })
      .catch((err) => {
        if (!(err instanceof DOMException && err.name === "AbortError")) {
          throw err;
        }
      });
    return () => {
      abortController.abort();
    };
  }

  @modelFlow
  fetchSchemaData = _async(function* (this: DatabaseState) {
    if (this.fetchingSchemaData || !this.connection) {
      return;
    }

    this.fetchingSchemaData = true;

    try {
      const instanceState = instanceCtx.get(this)!;
      const instanceId = instanceState.instanceId ?? "demo";
      const res = yield* _await(
        fetch(
          `${instanceState.serverUrl}/instances/${encodeURIComponent(
            instanceId
          )}/databases/${encodeURIComponent(this.name)}/schema`
        )
      );
      const schemaJson: {
        types: {name: string; columns?: {name: string; type: string; nullable: boolean; default: string | null}[]}[];
        version: string;
      } = yield* _await(res.json());

      const stringScalar: SchemaScalarType = {
        schemaType: "Scalar",
        id: "std::str",
        name: "std::str",
        escapedName: "std::str",
        module: "std",
        shortName: "str",
        abstract: false,
        builtin: true,
        from_alias: false,
        default: null,
        enum_values: null,
        arg_values: null,
        isSequence: false,
        knownBaseType: null,
        bases: [],
        constraints: [],
        annotations: [],
        isDeprecated: false,
      };

      const objects = new Map<string, SchemaObjectType>();
      const objectsByName = new Map<string, SchemaObjectType>();

      for (const t of schemaJson.types ?? []) {
        const properties: {[name: string]: SchemaProperty} = {};
        const pointers: SchemaProperty[] = [];
        for (const col of t.columns ?? []) {
          const prop: SchemaProperty = {
            schemaType: "Pointer",
            type: "Property",
            id: `${t.name}::${col.name}`,
            name: col.name,
            escapedName: col.name,
            module: "default",
            shortName: col.name,
            abstract: false,
            builtin: false,
            "@owned": true,
            target: stringScalar,
            source: null,
            required: !col.nullable,
            readonly: false,
            cardinality: "One",
            default: col.default,
            expr: null,
            secret: false,
            constraints: [],
            annotations: [],
            rewrites: [],
            isDeprecated: false,
            bases: [],
          };
          properties[col.name] = prop;
          pointers.push(prop);
        }

        const obj: SchemaObjectType = {
          schemaType: "Object",
          id: t.name,
          name: t.name,
          escapedName: t.name,
          module: "default",
          shortName: t.name,
          abstract: false,
          builtin: false,
          readonly: false,
          from_alias: false,
          expr: "",
          bases: [],
          extendedBy: [],
          ancestors: [],
          descendents: [],
          constraints: [],
          annotations: [],
          isDeprecated: false,
          insectionOf: null,
          unionOf: null,
          properties,
          links: {},
          pointers,
          indexes: [],
          accessPolicies: [],
          triggers: [],
        };

        objects.set(obj.id, obj);
        objectsByName.set(obj.name, obj);
      }

      runInAction(() => {
        this.schemaId = schemaJson.version ?? "api-schema";
        this.schemaLastMigration = null;
        this.schemaData = {
          objects,
          objectsByName,
          functions: new Map(),
          operators: new Map(),
          constraints: new Map(),
          scalars: new Map([[stringScalar.name, stringScalar]]),
          types: new Map(),
          pointers: new Map(),
          aliases: new Map(),
          globals: new Map(),
          annotations: new Map(),
          extensions: [],
          shortNamesByModule: new Map([["default", new Set(objectsByName.keys())]]),
        };
        this.objectCount = objects.size;
      });
    } finally {
      this.fetchingSchemaData = false;
    }
  });
}

export const DatabaseStateContext = createContext<DatabaseState>(null!);

export function useDatabaseState() {
  return useContext(DatabaseStateContext);
}
