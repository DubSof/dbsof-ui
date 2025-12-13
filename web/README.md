# DBSOF web app

This package contains the browser shell for the DBSOF UI. It is designed to be
wired up to any backend you choose; the UI runs entirely in the browser and
expects whatever API adapter you provide during integration time.

## Development

> **Prerequisites**: You will need to have Yarn 2+ installed, and have run the
> `yarn` command to install the workspace's dependencies.

To start the UI dev server:

```sh
yarn dev
```

The app is served at `http://localhost:3002/ui`.

The UI assumes a backend is available but does not start one for you. Point the
app at your own environment using the `VITE_GEL_SERVER_URL` (or an equivalent
override you configure) environment variable before running `yarn dev`.

## UI Tests

> **Prerequisites**: The UI tests use Selenium WebDriver to run tests on Chrome.
> You will need to have Chrome browser installed, and to have `chromedriver`
> installed and available in the system `PATH`.
>
> (Instructions to install `chromedriver`: https://www.selenium.dev/documentation/webdriver/getting_started/install_drivers/#3-the-path-environment-variable)

To run the UI tests:

```sh
yarn test
```

If there is already an instance of your dev backend running on port 5656, or
the UI dev server running on port 3000, then they will be used by the tests. If
not (or the tests are running in CI), the test runner will start temporary
instances of them for the duration of the tests.

By default the tests run `chromedriver` in headless mode, but to see the
Chrome window during the tests (eg. for debugging), run with the `--no-headless`
flag:

```sh
yarn test --no-headless
```

### Writing tests

The tests use the [Jest](https://jestjs.io) framework, with a custom
environment that provides an already configured instance of the `WebDriver`
class as the global variable `driver`. The following common webdriver API's
are also exposed as global variables: `By`, `until`, `Key`.
