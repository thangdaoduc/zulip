# Spec: Default User Email Settings

## Summary

Tắt tất cả email notifications mặc định cho user mới và realm mới.

## Requirements

### REQ-EMAIL-008: User Default Settings Override
- **Given**: Hệ thống Zulip có `USER_SETTINGS_DEFAULT_OVERRIDES` trong settings
- **When**: Thêm các settings sau vào `USER_SETTINGS_DEFAULT_OVERRIDES`:
  ```python
  'enable_offline_email_notifications': False,
  'enable_followed_topic_email_notifications': False,
  'enable_stream_email_notifications': False,
  'enable_digest_emails': False,
  'enable_login_emails': False,
  'enable_marketing_emails': False,
  'message_content_in_email_notifications': False,
  'email_notifications_batching_period_seconds': 0,
  ```
- **Then**: User mới sẽ có tất cả email notifications = False
- **Note**: Setting `email_notifications_batching_period_seconds = 0` vô hiệu hóa batching

### REQ-EMAIL-009: Realm Default Settings (Optional)
- **Given**: Realm model có các email-related settings
- **Check**: `zerver/models/realms.py` cho `Realm` model settings
- **If needed**: Set defaults trong `RealmUserDefault` model
- **Settings to disable**:
  - `digest_emails_enabled` (Realm level)
  - `send_welcome_emails` (Realm level)
  - `message_content_allowed_in_email_notifications` (Realm level)

### REQ-EMAIL-010: Existing User Settings
- **Given**: Các user đã tồn tại có thể đã bật email notifications
- **When**: Chạy script để tắt email notifications cho existing users (optional)
- **SQL Example**:
  ```sql
  UPDATE zerver_userprofile
  SET enable_offline_email_notifications = FALSE,
      enable_followed_topic_email_notifications = FALSE,
      enable_stream_email_notifications = FALSE,
      enable_digest_emails = FALSE,
      enable_login_emails = FALSE,
      enable_marketing_emails = FALSE,
      message_content_in_email_notifications = FALSE;
  ```
- **Note**: Chỉ thực hiện nếu muốn tắt cho tất cả existing users

## Verification

```bash
# Kiểm tra user mới có email notifications tắt không
cd /home/thangdao/Documents/hoanggia.proj/code/zulip
python3 -c "
import django
django.setup()
from zerver.models import RealmUserDefault
defaults = RealmUserDefault.objects.first()
if defaults:
    print('enable_offline_email_notifications:', defaults.enable_offline_email_notifications)
    print('enable_digest_emails:', defaults.enable_digest_emails)
    assert defaults.enable_offline_email_notifications == False, 'Email notification not disabled!'
    print('SUCCESS: Default email settings disabled')
else:
    print('No RealmUserDefault found - will be created on first realm creation')
"
```

## Impact

- **Positive**: User mới không bị làm phiền bởi email notifications
- **Positive**: Giảm tải cho hệ thống (không xử lý email logic)
- **Negative**: User không thể bật email notifications (nhưng hệ thống không gửi email anyway)
