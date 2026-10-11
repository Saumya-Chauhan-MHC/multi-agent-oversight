How I want this built:

- If you split this up, one agent per surface, and each owns its files. No two agents edit the
  same file.
- store/schema.py is the shared record format. Define it once, and tell me before changing it,
  because everything else is built against it.
- Nobody reports done without running the tests in tests/ and showing the result.
- The tests in tests/ are mine. Don't edit them.
- Whoever starts a server on 8077 owns it. Don't kill a process you didn't start.
- Get the store and the API working before the CLI.

Budget: 20 minutes, 1M tokens.
