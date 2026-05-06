# Tasks: Remove Email Dependency

## Task List

### Phase 1: Disable Email Workers

- [ ] **Task 1.1**: Disable EmailSendingWorker
  - File: `zerver/worker/email_senders_base.py`
  - Change: `@assign_queue("email_senders")` → `@assign_queue("email_senders", enabled=False)`
  - Verify: Worker không được register trong `worker_classes`

- [ ] **Task 1.2**: Disable MissedMessageWorker
  - File: `zerver/worker/missedmessage_emails.py`
  - Change: `@assign_queue("missedmessage_emails")` → `@assign_queue("missedmessage_emails", enabled=False)`
  - Note: Worker này xử lý batched email notifications

- [ ] **Task 1.3**: Disable DigestWorker
  - File: `zerver/worker/digest_emails.py`
  - Change: `@assign_queue("digest_emails")` → `@assign_queue("digest_emails", enabled=False)`
  - Note: Digest emails là email tổng hợp hàng ngày/tuần

- [ ] **Task 1.4**: Check and Disable DeferredEmailWorker
  - File: `zerver/worker/deferred_email_senders.py`
  - Action: Kiểm tra file có tồn tại không, nếu có thì thêm `enabled=False`
  - Current status: Need to verify

### Phase 2: Configure Dummy Email Backend

- [ ] **Task 2.1**: Update EMAIL_BACKEND setting
  - File: `zproject/computed_settings.py` hoặc `zproject/settings.py`
  - Add: `EMAIL_BACKEND = 'django.core.mail.backends.dummy.EmailBackend'`
  - Alternative: Dùng `'django.core.mail.backends.console.EmailBackend'` để debug

- [ ] **Task 2.2**: Set default FROM email
  - Add: `DEFAULT_FROM_EMAIL = 'noreply@localhost'`
  - Add: `SERVER_EMAIL = 'noreply@localhost'`

### Phase 3: Disable Default Email Notifications

- [ ] **Task 3.1**: Override default user settings
  - File: `zproject/settings.py`
  - Add: `USER_SETTINGS_DEFAULT_OVERRIDES` dictionary
  - Disable: All `*_email_notifications` settings
  - Disable: `enable_digest_emails`, `enable_login_emails`, `enable_marketing_emails`

- [ ] **Task 3.2**: Verify Realm default settings
  - Check: `zerver/models/realms.py` - Realm model có email settings không
  - Action: Có thể cần set default cho RealmUserDefault nếu cần

### Phase 4: Optional Cleanup

- [ ] **Task 4.1**: Disable Email Gateway (nếu không dùng)
  - Check: `EMAIL_GATEWAY_PATTERN` trong settings
  - Action: Comment out hoặc xóa config
  - Impact: Không thể gửi email → Zulip message

- [ ] **Task 4.2**: Clean up email-related management commands
  - Files: `zerver/management/commands/send_test_email.py`
  - `zerver/management/commands/send_password_reset_email.py`
  - Action: Có thể để nguyên, nhưng sẽ không hoạt động (expected)

### Phase 5: Testing

- [ ] **Task 5.1**: Test workers not started
  - Command: `./manage.py runworker --list`
  - Verify: Không thấy email workers trong list

- [ ] **Task 5.2**: Test new user default settings
  - Action: Tạo user mới qua API hoặc UI
  - Verify: Email notifications = False

- [ ] **Task 5.3**: Test functionality without email
  - Test: Gửi message, tạo stream, add user
  - Verify: Không có lỗi liên quan đến email

- [ ] **Task 5.4**: Test password reset (expected failure)
  - Action: Thử reset password
  - Verify: Không gửi được email (dummy backend)
  - Note: Cần phương án thay thế (admin reset)

## Dependencies

- None (các tasks có thể làm độc lập trong cùng phase)

## Parallelizable Tasks

- Tất cả tasks trong Phase 1 có thể làm song song
- Task 2.1 và 2.2 có thể làm song song
- Task 3.1 và 3.2 có thể làm song song

## Verification Commands

```bash
# Kiểm tra workers
cd /home/thangdao/Documents/hoanggia.proj/code/zulip
./manage.py runworker --list | grep -i email  # Should return nothing

# Kiểm tra settings
./manage.py shell -c "from django.conf import settings; print(settings.EMAIL_BACKEND)"

# Kiểm tra user defaults
./manage.py shell -c "from zerver.models import RealmUserDefault; print(RealmUserDefault.objects.first().enable_offline_email_notifications)"
```
