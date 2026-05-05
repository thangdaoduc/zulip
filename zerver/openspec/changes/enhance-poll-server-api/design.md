# Design: Enhance Poll Server API

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      Poll Lifecycle                              │
│                                                                  │
│  CREATE                          VOTE / ADD OPTION               │
│  POST /api/v1/messages           POST /api/v1/submessage         │
│  content: "/poll Q?\nA\nB"       content: {type: "vote", ...}    │
│  widget_content: optional        content: {type: "new_option"}   │
│  extra_data {                    content: {type: "close"}  NEW   │
│    question, options,            content: {type: "open"}   NEW   │
│    multi_select?,                │
│    allow_new_options? }          │
│         │                              │                          │
│         ▼                              ▼                          │
│  ┌──────────────────┐    ┌──────────────────────────────┐       │
│  │ widget.py        │    │ views/submessage.py          │       │
│  │ get_widget_data()│    │ process_submessage()         │       │
│  │ → PollData       │    │ 1. Get widget_type           │       │
│  │ → extra_data     │    │ 2. Check if poll closed NEW  │       │
│  │ → SubMessage #1  │    │ 3. validate_poll_data()      │       │
│  │   (widget meta)  │    │ 4. Append timestamp          │       │
│  └──────────────────┘    │ 5. do_add_submessage()       │       │
│                          └──────────┬───────────────────┘       │
│                                     │                            │
│                          ┌──────────▼───────────────────┐       │
│                          │ validator.py                 │       │
│                          │ validate_poll_data()         │       │
│                          │  - vote: validate key, ±1   │       │
│                          │  - new_option: validate idx  │       │
│                          │    + check allow_new_options │       │
│                          │  - question: author-only     │       │
│                          │  - close: author-only  NEW   │       │
│                          │  - open:  author-only  NEW   │       │
│                          └──────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────┘
```

## Server-Side Changes

### 1. `zerver/lib/widget.py` — Parse new extra_data fields

**Current `PollData` dataclass:**
```python
@dataclass
class PollData:
    question: str
    options: list[str]
```

**Proposed:**
```python
@dataclass
class PollData:
    question: str
    options: list[str]
    multi_select: bool = False
    allow_new_options: bool = True
```

**Changes:**
- Add `multi_select` and `allow_new_options` optional fields with defaults
- These are NOT parsed from the `/poll` command text (no text syntax for them)
- They are only settable via `widget_content` API parameter when sending the message
- `do_widget_post_save_actions()` already passes through arbitrary `extra_data` dicts, so no changes needed there

### 2. `zerver/lib/validator.py` — Validate new op types and enforce constraints

**Current `validate_poll_data()`:**
- Validates `vote`, `question`, `new_option` types

**Proposed additions:**

```python
def validate_poll_data(poll_data: object, is_widget_author: bool) -> None:
    # ... existing code for vote, question, new_option ...

    if poll_data["type"] == "close":
        if not is_widget_author:
            raise ValidationError("You can't close a poll unless you are the author.")
        checker = check_dict_only([("type", check_string)])
        checker("poll data", poll_data)
        return

    if poll_data["type"] == "open":
        if not is_widget_author:
            raise ValidationError("You can't reopen a poll unless you are the author.")
        checker = check_dict_only([("type", check_string)])
        checker("poll data", poll_data)
        return

    # Also: in new_option validation, if allow_new_options is False
    # and the user is not the author, reject
```

**Key decision on `allow_new_options` enforcement:**
- The validator does NOT have access to the initial extra_data (it only sees the current submessage op)
- Therefore, `allow_new_options` enforcement must happen in `views/submessage.py`, not in the validator
- The validator only validates schema; the view enforces business logic

### 3. `zerver/views/submessage.py` — Enforce business logic

**Current flow:**
1. Parse widget_data JSON
2. Get widget_type
3. Validate via `validate_poll_data()`
4. Add timestamp to widget_data
5. Call `do_add_submessage()`

**Proposed flow:**
1. Parse widget_data JSON
2. Get widget_type
3. **NEW: Check if poll is closed** (scan submessages for `close` without subsequent `open`)
4. If poll is closed and op is `vote` or `new_option`, reject with error
5. **NEW: Check `allow_new_options`** (scan initial submessage extra_data)
6. If `allow_new_options` is false and op is `new_option` and user is not author, reject
7. Validate via `validate_poll_data()`
8. Add timestamp to widget_data
9. Call `do_add_submessage()`

**Helper function to check poll state:**

```python
def get_poll_state(message_id: int) -> dict[str, Any]:
    """Scan submessages to determine current poll state.
    Returns {
        "is_closed": bool,
        "allow_new_options": bool,
    }
    """
    submessages = SubMessage.objects.filter(
        message_id=message_id, msg_type="widget"
    ).order_by("id")

    is_closed = False
    allow_new_options = True

    for sub in submessages:
        data = orjson.loads(sub.content)
        # First submessage has widget_type + extra_data
        if "widget_type" in data:
            extra = data.get("extra_data", {})
            allow_new_options = extra.get("allow_new_options", True)
        elif data.get("type") == "close":
            is_closed = True
        elif data.get("type") == "open":
            is_closed = False

    return {"is_closed": is_closed, "allow_new_options": allow_new_options}
```

**Note:** This function queries the DB again, but it's necessary because `process_submessage` needs to know the current poll state before allowing the op. The `SubMessage.objects.filter()` call is efficient since it's indexed by `message_id`.

### 4. `zerver/tests/test_widgets.py` and new test file

- Add tests for `close`/`open` op types
- Add tests for `allow_new_options: false` enforcement
- Add tests for `multi_select: true` in extra_data
- Add tests for non-author attempting close/open (should fail)
- Add tests for voting on a closed poll (should fail)

### 5. Timestamp field

**Already implemented.** Line 61 of `views/submessage.py`:
```python
widget_data["timestamp"] = time.time()
```

This adds a Unix timestamp to every submessage op. The client can read this from the submessage content JSON to know when each vote was cast.

---

## Client Documentation: API Changes for Flutter

### Overview

The Zulip poll API now supports the following additional fields and op types. All changes are **backward compatible** — existing clients that ignore these fields will continue to work.

### New Fields in Initial extra_data

When creating a poll via `POST /api/v1/messages`, you can include `widget_content` with these new fields:

```json
{
  "widget_type": "poll",
  "extra_data": {
    "question": "What is your favorite color?",
    "options": ["Red", "Green", "Blue"],
    "multi_select": false,
    "allow_new_options": true
  }
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `multi_select` | `bool` | `false` | If `true`, users can vote for multiple options. If `false`, voting for one option removes any existing vote. |
| `allow_new_options` | `bool` | `true` | If `true`, any user can add new options. If `false`, only the poll author can add options. |

### New Submessage Op Types

#### `close` — Close the poll

Only the poll author can close a poll. Once closed, no votes or new options are accepted.

```json
POST /api/v1/submessage
{
  "message_id": 123,
  "msg_type": "widget",
  "content": "{\"type\": \"close\"}"
}
```

**Error responses:**
- `400` — "You can't close a poll unless you are the author."

#### `open` — Reopen a closed poll

Only the poll author can reopen a poll.

```json
POST /api/v1/submessage
{
  "message_id": 123,
  "msg_type": "widget",
  "content": "{\"type\": \"open\"}"
}
```

**Error responses:**
- `400` — "You can't reopen a poll unless you are the author."

### New Field in Every Submessage Op: `timestamp`

**Already present in current API.** Every submessage op (vote, new_option, close, open, question) includes a `timestamp` field (Unix epoch seconds) added by the server:

```json
{
  "type": "vote",
  "key": "1,1",
  "vote": 1,
  "timestamp": 1714800000.123
}
```

Clients should read this from the parsed submessage content to determine when each vote was cast.

### Server-Enforced Behaviors

| Scenario | Behavior |
|----------|----------|
| Vote on a closed poll | Server returns `400` with error message |
| Add option on a closed poll | Server returns `400` with error message |
| Add option when `allow_new_options: false` (non-author) | Server returns `400` with error message |
| Close/open by non-author | Server returns `400` with error message |

### Recommended Client Implementation

```
┌─────────────────────────────────────────────┐
│  Flutter Client: PollContentNode            │
├─────────────────────────────────────────────┤
│  question: String                           │
│  options: List<PollOption>                  │
│  isMyPoll: bool                             │
│  isMultiSelect: bool        ← wire to extra │
│  allowNewOptions: bool      ← wire to extra │
│  isClosed: bool             ← replay ops    │
│  creatorId: int             ← from sender   │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│  Flutter Client: PollOption                 │
├─────────────────────────────────────────────┤
│  id: int                                    │
│  key: String                                │
│  text: String                               │
│  voterIds: List<int>                        │
│  voteTimestamps: Map<int, int> ← NEW        │
│     (userId → unix timestamp)               │
└─────────────────────────────────────────────┘
```

**Parser changes (`content_parser.dart`):**

1. In `_parsePoll()`, read `multi_select` and `allow_new_options` from the initial widget submessage extra_data.
2. Replay `close` and `open` ops to determine `isClosed` state.
3. For each `vote` op, extract `timestamp` from the submessage content and populate `voteTimestamps`.

**UI changes (`poll_widget.dart`):**

1. If `isClosed == true`, disable voting UI and show "Poll closed" indicator.
2. If `allowNewOptions == false`, hide the "add option" input for non-authors.
3. If `isMultiSelect == true`, do not retract existing votes when selecting a new option.
4. Show vote timestamps optionally (e.g., in a detail view).

**Vote service changes (`poll_vote_service.dart`):**

1. Check `isClosed` before sending vote — reject locally if already closed.
2. The server will also reject, but local check provides better UX.
3. For multi-select, skip the retraction logic that currently removes votes from other options.
