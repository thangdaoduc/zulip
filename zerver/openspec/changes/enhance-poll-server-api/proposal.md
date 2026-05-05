# Enhance Poll Server API

## Problem

The current Zulip poll system has several limitations that prevent rich polling experiences:

1. **No vote timestamps** — Clients cannot determine when a vote was cast, only who voted.
2. **No multi-select support** — Polls always behave as single-select; there is no way to create "choose all that apply" polls.
3. **No option gating** — Anyone can add new options to a poll at any time. Poll creators cannot restrict this.
4. **No close/open mechanism** — Polls cannot be formally closed to prevent further voting, nor reopened after closing.

These limitations are particularly impactful for mobile clients that need richer poll semantics than the web widget provides.

## Proposed Solution

Extend the server-side poll submessage API with:

1. **`timestamp` field** — Already added by the server to every submessage (`views/submessage.py:61`). Clients can now replay this from the submessage content to know exactly when each vote occurred.

2. **`multi_select` flag in extra_data** — A boolean field in the initial widget `extra_data` that tells clients whether the poll allows multiple selections. Defaults to `false` for backward compatibility.

3. **`allow_new_options` flag in extra_data** — A boolean field controlling whether non-authors can add new options. Defaults to `true` for backward compatibility. Server validates this on `new_option` ops.

4. **`close` / `open` submessage types** — New op types that only the poll author can send. When closed, the server rejects `vote` and `new_option` ops from all users.

## Scope

### In scope
- Server-side validation changes in `zerver/lib/validator.py`
- Server-side enforcement in `zerver/views/submessage.py`
- Server-side parsing of new extra_data fields in `zerver/lib/widget.py`
- New submessage op types: `close`, `open`
- Documentation for Flutter client on how to use the new API

### Out of scope
- Database schema changes (polls still use SubMessage rows, no new model)
- Changes to the web frontend poll widget
- Changes to existing `vote` or `new_option` payload structure (backward compatible)
- Migration of existing polls

## Success Criteria

- A poll can be created with `multi_select: true` and clients correctly allow multiple votes
- A poll can be created with `allow_new_options: false` and non-authors are rejected from adding options
- A poll can be closed by its author, rejecting further votes and new options
- A poll can be reopened by its author after closing
- All submessage ops include a `timestamp` field that clients can use to determine vote timing
- Existing polls (without new fields) continue to work exactly as before
