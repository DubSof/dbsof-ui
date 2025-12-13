# DBSOF UI

This monorepo packages a reusable studio-style UI that can be wired up to any
infrastructure backend. The codebase keeps the full component library intact
while moving provider-specific integrations behind a platform abstraction so it
can act as a starting point for new projects.

## Workspaces

This repo is organised using yarn workspaces as follows:

- `/web`: The main UI shell that wires together routing, state management, and
  shared components. See <./web/readme.md> for build and development steps.
- `/shared`: Shared component packages, including the graph dependency
  visualiser, terminal, schema graph, inspector, and editor integrations that
  can be reused across different studio deployments.
