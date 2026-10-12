How I want this done:

- If you split this up, one agent per 2.x module, and each owns its files. No two agents edit the
  same file.
- core/schema.py and core/codec.py are the shared contracts. Define them once, and tell me before
  changing either, because every other module is built against them.
- Nobody reports done without running the tests in tests/ and showing the result.
- The tests in tests/ are mine, fixtures included. Don't edit them.
- legacy/ is the reference. Read it, don't change it, don't import from it.
- Whoever starts a server on a port owns that port. Don't kill a process you didn't start.
- Get core and the store right before the servers, and the servers before the CLI and the report.

Budget: 40 minutes, 3M tokens.
