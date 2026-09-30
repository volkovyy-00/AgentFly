# Flight Recorder

See `SPEC.md` (source of truth) and `AGENTS.md` (working rules).

## Credentials setup (every developer, once per machine)

Real Neo4j credentials never go in this repo. The project `.env` holds only a
FAKE demo secret used as bait. The server reads the real ones from
`~/.config/flightrecorder/.env`.

1. Get the Aura credentials file (the `Neo4j-...-Created-....txt` download).
   If the instance is shared, get it from your teammate through a password
   manager or a one-time secret link. Never through git or an AI chat.
2. Run in a normal terminal (not one the agent is using):

   ```
   scripts/setup_credentials.sh /path/to/Neo4j-xxxx.txt
   ```

   It creates the folder (700), copies the file (600) and prints key names
   and permissions only, never values.
3. Check that nothing leaked into the environment: `env | grep -i neo4j`
   must print nothing.
4. Delete the downloaded file when you no longer need it.
5. Start the server in a separate terminal, not in Cursor's terminal.
