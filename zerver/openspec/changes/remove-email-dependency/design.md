# Design: Remove Email Dependency

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│  TRƯỚC: Có Email                                       │
├─────────────────────────────────────────────────────────┤
│  Workers: email_senders, missedmessage_emails,         │
│           digest_emails, deferred_email_senders          │
│  Backend: SMTP (django.core.mail.backends.smtp)        │
│  Notifications: enable_*_email_notifications = True     │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  SAU: Không Email                                      │
├─────────────────────────────────────────────────────────┤
│  Workers: (disabled - enabled=False)                    │
│  Backend: dummy (django.core.mail.backends.dummy)      │
│  Notifications: enable_*_email_notifications = False    │
│  UserProfile: vẫn giữ email field (fake: user123@realm)│
└─────────────────────────────────────────────────────────┘
```

## Technical Approach

### 1. Worker Disabling

Sử dụng parameter `enabled=False` trong decorator `@assign_queue`:

**Files to modify:**
- `zerver/worker/email_senders_base.py` - EmailSendingWorker
- `zerver/worker/missedmessage_emails.py` - MissedMessageWorker
- `zerver/worker/digest_emails.py` - DigestWorker
- `zerver/worker/deferred_email_senders.py` - DeferredEmailWorker (if exists)

**Code change pattern:**
```python
# Before:
@assign_queue("email_senders")
class EmailSendingWorker(LoopQueueProcessingWorker):

# After:
@assign_queue("email_senders", enabled=False)
class EmailSendingWorker(LoopQueueProcessingWorker):
```

### 2. Django Email Backend Configuration

**File: `zproject/computed_settings.py` or `zproject/settings.py`**

```python
# Thay đổi từ SMTP sang dummy backend
EMAIL_BACKEND = 'django.core.mail.backends.dummy.EmailBackend'

# Hoặc dùng console backend để debug (log ra console thay vì gửi)
# EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Cấu hình default from email
DEFAULT_FROM_EMAIL = 'noreply@localhost'
SERVER_EMAIL = 'noreply@localhost'
```

### 3. Default User Settings Override

**File: `zproject/settings.py`**

```python
# Tắt tất cả email notifications mặc định cho user mới
if not hasattr(settings, 'USER_SETTINGS_DEFAULT_OVERRIDES'):
    USER_SETTINGS_DEFAULT_OVERRIDES = {}

USER_SETTINGS_DEFAULT_OVERRIDES.update({
    'enable_offline_email_notifications': False,
    'enable_followed_topic_email_notifications': False,
    'enable_stream_email_notifications': False,
    'enable_digest_emails': False,
    'enable_login_emails': False,
    'enable_marketing_emails': False,
    'message_content_in_email_notifications': False,
    'email_notifications_batching_period_seconds': 0,  # Disable batching
})
```

### 4. Email Gateway Disabling (Optional)

Nếu không dùng tính năng gửi email → Zulip message:

**File: `zproject/settings.py`**
```python
# Comment hoặc xóa các config này
# EMAIL_GATEWAY_PATTERN = ...
# EMAIL_GATEWAY_BOT = ...
# EMAIL_GATEWAY_EXAMPLE = ...
```

### 5. UserProfile Email Handling

**Quan trọng: Giữ nguyên cấu trúc UserProfile**

```python
# Trong zerver/models/users.py - KHÔNG SỬA
class UserProfile(AbstractBaseUser, PermissionsMixin, UserBaseSettings):
    USERNAME_FIELD = "email"  # ← Giữ nguyên, dùng fake email
    
    delivery_email = models.EmailField(blank=False, db_index=True)
    email = models.EmailField(blank=False, db_index=True)  # ← Fake email
```

**Ensure fake email domain is configured:**
```python
# Trong settings.py
FAKE_EMAIL_DOMAIN = 'zulip.local'  # ← Domain cho fake email
```

## Database Migration

**Không cần migration** - Chúng ta giữ nguyên cấu trúc database, chỉ tắt tính năng ở tầng application.

## Testing Strategy

1. **Worker Check**: Chạy `./manage.py runworker` và xác nhận không có email workers
2. **Notification Check**: Tạo user mới và kiểm tra settings mặc định
3. **Functionality Check**: Test gửi message, tạo stream, invitation (không email)
4. **Password Reset**: Test và xác nhận không gửi được email (expected behavior)

## Rollback Plan

Nếu cần quay lại:
```bash
git revert <commit-hash>
# Hoặc đơn giản:
git checkout HEAD~1 -- zerver/worker/ zproject/settings.py
```

## Performance Impact

**Positive:**
- Ít workers chạy → tiết kiệm tài nguyên
- Không SMTP connections → giảm latency
- Ít database queries liên quan đến email queues

**Negative:**
- None (chúng ta không dùng email nên không có tác động tiêu cực)
