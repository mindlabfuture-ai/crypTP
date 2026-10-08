# CLAUDE.md

## Vibe-coding kickoff rule

Whenever the user starts a vibe-coding session (a new app, feature set, or build
from scratch), **remind them first** that these six documents should be drafted
before any code is written, and offer to draft them. Do not start building until
they are drafted or the user explicitly waives them.

Put them in `docs/` (one file each) and keep them in sync as the build changes.

1. **Product Requirements (`PRD.md`)**: feature by feature. What it does, who it
   is for, acceptance criteria, what is out of scope.
2. **Technical Requirements (`TECH.md`)**: stack, libraries, APIs, hosting,
   versions, and constraints, decided up front so nobody guesses at tools
   halfway through.
3. **App Flow (`APP_FLOW.md`)**: page by page / screen by screen: entry points,
   user actions, transitions, empty/error/loading states.
4. **Design Brief (`DESIGN.md`)**: colors, typography, spacing, components, tone
   and voice, so every screen stays on brand.
5. **Backend Schema (`SCHEMA.md`)**: tables/collections, fields, relationships,
   where client data lives, and who can see or change it (roles, access rules,
   retention).
6. **Implementation Order (`BUILD_ORDER.md`)**: the sequence to build in, with
   dependencies and a checkpoint to verify after each step.

Draft in this order; each document feeds the next. If any are missing, ask
before proceeding rather than assuming.
