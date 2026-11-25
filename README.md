# The Uncle Whisperer

**A relative sent you a message before Thanksgiving dinner. Before you answer, this agent reads it for you.**

Live demo: https://uncle-whisperer-b6wqm.sprites.app/

You paste the message your relative wrote to you. The agent gives you three things:

1. **What is really bothering the relative who wrote the message.** The agent quotes the exact words that gave it away.
2. **What you should not answer**, and what that answer would do to your relative.
3. **One sentence you can send back.**

The agent also remembers each relative. When the same relative writes to you again, the agent tells you whether the same thing is bothering them as last time.

Built by Zion Cohen for Fly.io Hacksgiving, November 23–29, 2026.

## An example

The scene: for thirty years your mother cooked Thanksgiving dinner. This year you offered to host and cook, for the first time. Your mother writes to you:

> Don't go to any trouble honey. Dad and I will eat something before we come, so you really don't need to cook that much. I'll bring my stuffing just in case.

You are tempted to answer your mother: "Fine, then I'll cook less." The agent reads your mother's message first, and tells you:

| | The agent's answer to you |
|---|---|
| What is really bothering your mother | Your mother feels pushed out of her role as the person who feeds the family. She needs to know she still has a place at the table. |
| The words that gave it away | "I'll bring my stuffing just in case" |
| What you should not answer | "Okay, we'll just order pizza then." That answer confirms to your mother that nobody needs her. |
| One sentence you can send back | "We'd love to have your stuffing. It wouldn't be Thanksgiving without it." |

Your mother's message looks like it is about food. It is about her place in the family. The agent answers that, and not the food.

## Try it in one minute

1. Open the live demo: https://uncle-whisperer-b6wqm.sprites.app/
2. Press the button **Your uncle complains about the seating**. The agent fills the form with a sample message from Uncle Ray, and shows you the scene: what happened between you and Uncle Ray before he wrote.
3. Press **Read this message for me**. The agent answers in about 15 seconds.
4. To see the agent remember Uncle Ray: keep "Uncle Ray" in the first box, replace the message with `Saw the photos from your dinner with the neighbors. Looked like a great table. Plenty of room.` and press **Read this message for me** again. The agent now adds a part called **The agent remembers this relative**, and connects the new message to the earlier one.

The first press after a quiet period takes a few seconds longer, because the Sprite was asleep and wakes up for you.

## How the agent meets the Hacksgiving rules

| Rule | How this agent meets it |
|---|---|
| Runs on a Fly.io Sprite | The live demo is the Sprite. `app.py` runs there as a Sprite service on port 8080, and the Sprite wakes when you open the page. |
| Uses at least one Sprites connector | The agent reaches its language model only through the **Sprites OpenRouter connector** (the managed one). The bottom of the demo page shows the live answer of the Sprites gateway. You can also open [/api/connected](https://uncle-whisperer-b6wqm.sprites.app/api/connected). |
| Built during Hacksgiving week | I wrote all of the code on November 25, 2026. The commit history of this repository starts on that day. |

## How it works

```
your browser ──► app.py on the Sprite ──► Sprites gateway ──► OpenRouter ──► language model
                     │                    (OpenRouter connector)
                     ▼
        memory.json on the Sprite's disk
        (a short note about each relative)
```

- **`app.py`** is one Python file that uses only the standard library. It serves the page, takes the message you paste, and asks the language model to read it.
- **The connector.** At start, `app.py` asks the Sprites gateway (`https://api.sprites.dev/v1/gateway/list`) which connectors this Sprite may use. It then sends every model request to the gateway address of the OpenRouter connector. The gateway recognizes the Sprite and adds the credential. The code in this repository holds no API key, and neither does the Sprite.
- **Least access.** I set the access policy of the connector so that only a Sprite whose name starts with `uncle-` may use it, and only for two paths: `/v1/chat/completions` and `/v1/models`.
- **Memory.** After each reading, the agent writes a short note on the Sprite's disk: the name of the relative, the first 300 characters of the relative's message, and what was bothering the relative. The Sprite keeps its disk when it sleeps. The next time you paste a message from the same relative, the agent gives the language model the last three notes about that relative.
- **The models.** The agent uses free models on OpenRouter, so the demo costs nothing to run. Free models are sometimes busy. When a model does not answer, the agent tries the next model on its list.
- **Limits.** The agent reads at most 300 messages a day in total, and at most 20 messages an hour from one browser.

## Run your own copy on a Sprite

You need a Fly.io account and the `sprite` command-line tool ([installation guide](https://docs.fly.io/sprites/cli/installation)).

```sh
sprite login
sprite create --skip-console uncle-whisperer

# Enable the managed OpenRouter connector for your organization,
# then allow Sprites whose name starts with "uncle-" to use it.
sprite api oauth/connections/provision -- -X POST \
  -H "Content-Type: application/json" -d '{"provider":"openrouter"}'
# Copy the connection id from the answer into <id>:
sprite api oauth/connections/<id> -- -X PUT \
  -H "Content-Type: application/json" \
  -d '{"access_policy":{"name_prefix":"uncle-","allowed_endpoints":["/v1/chat/completions","/v1/models"]}}'

# Copy the two files to the Sprite and start the agent as a service.
sprite exec -s uncle-whisperer -- mkdir -p /home/sprite/uncle
sprite exec -s uncle-whisperer -- bash -c "cat > /home/sprite/uncle/app.py" < app.py
sprite exec -s uncle-whisperer -- bash -c "cat > /home/sprite/uncle/index.html" < index.html
sprite exec -s uncle-whisperer -- sprite-env services create uncle \
  --cmd python3 --args /home/sprite/uncle/app.py --http-port 8080

# Make the page public and print its address.
sprite config update -s uncle-whisperer --url-auth public
sprite info -s uncle-whisperer
```

Settings you can change with environment variables: `UNCLE_MODELS` (a comma-separated list of OpenRouter model names, tried in order), `UNCLE_MAX_READS_PER_DAY`, and `UNCLE_DATA_DIR`.

## What to know before you paste a real message

- The demo is public. Do not paste anything private.
- The agent keeps the first 300 characters of each message, so that it can remember the relative. Your browser gets a random number, and the agent shows your relatives only to that browser.
- The message goes to a free model on OpenRouter. Providers of free models may keep what they receive.
- The agent reads words. It does not know your family. Treat its answer as a second opinion from someone who read the message calmly, and decide yourself what to send.

## Where the idea comes from

I work on BEZEN, a layer that reads, from the words a person writes, what is really bothering that person, and says what not to do next. For Hacksgiving I wrote this agent from scratch around the one week of the year when almost everyone gets a message like Uncle Ray's.

## License

MIT. See [LICENSE](LICENSE).
