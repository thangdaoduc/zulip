# Tasks: Enhance Poll Server API

## Phase 1: Server-Side Changes

### 1.1 Extend PollData dataclass

**File:** `zerver/lib/widget.py`

- [x] Add `multi_select: bool = False` field to `PollData` dataclass
- [x] Add `allow_new_options: bool = True` field to `PollData` dataclass
- [x] Verify `asdict()` correctly serializes the new fields into extra_data

### 1.2 Add close/open validation

**File:** `zerver/lib/validator.py`

- [x] Add validation case for `type: "close"` — requires author-only, schema: `{type: string}`
- [x] Add validation case for `type: "open"` — requires author-only, schema: `{type: string}`
- [x] Ensure existing `vote`, `question`, `new_option` validation is unchanged

### 1.3 Add poll state checking helper

**File:** `zerver/views/submessage.py` (or a new `zerver/lib/poll_state.py`)

- [x] Create `get_poll_state(message_id)` function that:
  - Queries all SubMessage rows for the message
  - Reads initial extra_data for `allow_new_options` (default true)
  - Replays `close`/`open` ops in order to determine `is_closed`
  - Returns `{is_closed: bool, allow_new_options: bool}`

### 1.4 Enforce poll state in process_submessage

**File:** `zerver/views/submessage.py`

- [x] After parsing widget_data, call `get_poll_state()` if widget_type is "poll"
- [x] If `is_closed` and op type is `vote` or `new_option`, raise `JsonableError` with "This poll is closed."
- [x] If `allow_new_options` is false and op type is `new_option` and user is not author, raise `JsonableError` with "This poll does not allow new options."
- [x] Ensure these checks run BEFORE `validate_poll_data()` so schema validation is not reached for rejected ops

### 1.5 Server-side tests

**File:** `zerver/tests/test_widgets.py` and/or `zerver/tests/test_submessage.py`

- [x] Test: author can close poll with `type: "close"`
- [x] Test: non-author cannot close poll (gets 400 error)
- [x] Test: author can reopen poll with `type: "open"`
- [x] Test: non-author cannot reopen poll (gets 400 error)
- [x] Test: voting on closed poll is rejected
- [x] Test: adding option to closed poll is rejected
- [x] Test: adding option when `allow_new_options: false` is rejected for non-author
- [x] Test: author can still add option when `allow_new_options: false`
- [x] Test: poll with `multi_select: true` has field in initial submessage extra_data
- [x] Test: existing polls (no new fields) continue to work
- [x] Test: timestamp is present in every submessage content

## Phase 2: Flutter Client Documentation

### 2.1 Update PollContentNode model

**File:** `packages/feature_chat/lib/src/domain/entities/content/content_node.dart`

- [x] Add `isMultiSelect: bool` to `PollContentNode` (already exists, verify it's wired)
- [x] Add `allowNewOptions: bool` to `PollContentNode` (default `true`)
- [x] Add `isClosed: bool` to `PollContentNode` (default `false`)
- [x] Add `voteTimestamps: Map<int, int>` to `PollOption` (userId → unix timestamp)

### 2.2 Update content parser

**File:** `packages/feature_chat/lib/src/domain/entities/content/content_parser.dart`

- [x] In `_parsePoll()`, read `multi_select` from initial widget submessage extra_data
- [x] Read `allow_new_options` from initial widget submessage extra_data
- [x] Replay `close` ops to set `isClosed = true`
- [x] Replay `open` ops to set `isClosed = false`
- [x] For each `vote` submessage, extract `timestamp` and add to `voteTimestamps` map for the corresponding option

### 2.3 Update poll vote service

**File:** `packages/feature_chat/lib/src/data/services/poll_vote_service.dart`

- [x] Check `pollNode.isClosed` before sending vote — throw or return early if closed
- [x] If `isMultiSelect` is true, skip the existing vote retraction logic (lines 25-37)
- [x] No need to send `ts` field — server already adds `timestamp` to every submessage

### 2.4 Update poll widget UI

**File:** `packages/feature_chat/lib/src/presentation/widgets/conversation/content/poll_widget.dart`

- [x] If `isClosed == true`, show "Poll closed" indicator and disable option tap
- [x] If `allowNewOptions == false` and `!isMyPoll`, hide "add new option" UI (if implemented)
- [x] Show vote counts with optional timestamp detail
- [x] Multi-select: update tap behavior to allow multiple selections (toggle per option)

### 2.5 Update reaction handler mixin

**File:** `packages/feature_chat/lib/src/presentation/screens/shared/reaction_handler_mixin.dart`

- [x] In `castPollVote()`, check `isClosed` before calling `service.castVote()`
- [x] Show user-facing error if poll is closed
- [x] Pass `isMultiSelect` to vote service so it knows whether to retract

### 2.6 Client-side tests

- [x] Test: parser correctly reads `multi_select` from extra_data
- [x] Test: parser correctly reads `allow_new_options` from extra_data
- [x] Test: parser correctly determines `isClosed` from close/open ops
- [x] Test: parser populates `voteTimestamps` from submessage timestamps
- [x] Test: vote service rejects vote on closed poll
- [x] Test: vote service does not retract votes when `isMultiSelect` is true
- [x] Test: poll widget shows disabled state when closed
- [x] Test: poll widget allows multi-select when `isMultiSelect` is true
