# AI_devs 4: agent tasks

My solutions to the practical tasks from **AI_devs 4: Builders**, a Polish
course on building production-style AI agents. Each task is a small mission
against the course API (`hub.ag3nts.org`): an agent has to gather information,
use tools, and submit an answer to a `/verify` endpoint.

The solutions are standalone Python scripts. Four of them run **Claude**
(Anthropic API) as an agent with tool use; the rest solve the task with plain
Python where an LLM wasn't needed.

## Tasks

| Task | What the agent does | Techniques |
|---|---|---|
| [S01E02](S01E02/main.py) | Works out which suspect was seen near a power plant using location, access-level and power-plant lookup tools | Claude tool use, agent loop |
| [S01E03](S01E03/main.py) | Acts as a logistics assistant that holds a conversation with an operator, tracks a package and quietly redirects it | Flask webhook, ngrok tunnel, per-session conversation memory, tool use |
| [S02E04](S02E04/main.py) | Searches a mailbox API to extract a date, a password and a security code | Tool use over a paginated search API |
| [S02E05](S02E05/main.py) | Reads a map image to find the right sector, then sends drone instructions | Claude vision, tool use |
| [S03E01](S03E01/main.py) | Finds anomalies in ~10k sensor readings, including operator notes that contradict the data | Range and consistency checks, keyword analysis of free-text notes |
| [S03E02](S03E02/main.py) | Fixes and runs a firmware binary on a restricted Linux VM through a shell API | Scripted shell automation |
| [S03E04](S03E04/main.py) | Exposes search tools that another agent calls during a negotiation | Flask tool endpoints, ngrok, keyword stemming and matching over CSV data |
| [S03E05](S03E05/main.py) | Plans the cheapest route across a map with vehicles, fuel and food limits | Tool discovery, BFS with resource constraints |
| [S04E02](S04E02/main.py) | Configures a wind-turbine schedule from a weather forecast within a 40-second window | Time-boxed API orchestration with threads |

## Running a task

Requires Python 3.10+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install anthropic flask pyngrok httpx certifi

cp .env.example .env   # then fill in the keys
export $(grep -v '^#' .env | xargs)

python S03E05/main.py
```

### Environment variables

| Variable | Used for |
|---|---|
| `AG3NTS_API_KEY` | Course API key (all tasks) |
| `ANTHROPIC_API_KEY` | Claude API key (tasks that use an LLM) |
| `ANTHROPIC_BASE_URL`, `ANTHROPIC_FOUNDRY_BASE_URL`, `ANTHROPIC_FOUNDRY_API_KEY` | Optional: route Claude calls through a proxy |
| `DEFAULT_LLM_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL` | Optional: override the model |

S01E03 and S03E04 start a local Flask server and expose it with ngrok, so they
also need an [ngrok](https://ngrok.com) account configured locally.

Task data (sensor readings, CSVs, map image) is included next to the scripts
that use it.
