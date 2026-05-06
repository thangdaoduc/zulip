# Spec: Email Backend Configuration

## Summary

Cấu hình Django email backend thành dummy để đảm bảo không có email nào được gửi ra ngoài.

## Requirements

### REQ-EMAIL-005: Dummy Email Backend
- **Given**: Hệ thống Zulip có cấu hình EMAIL_BACKEND
- **When**: Set `EMAIL_BACKEND = 'django.core.mail.backends.dummy.EmailBackend'`
- **Then**: Mọi cuộc gọi đến `send_mail()` sẽ không làm gì cả (no-op)
- **Then**: Không có SMTP connection nào được thiết lập
- **Alternative**: Có thể dùng `'django.core.mail.backends.console.EmailBackend'` để log ra console (debug only)

### REQ-EMAIL-006: Default FROM Email
- **Given**: Hệ thống Zulip cần FROM email cho các email nội bộ
- **When**: Set `DEFAULT_FROM_EMAIL = 'noreply@localhost'`
- **When**: Set `SERVER_EMAIL = 'noreply@localhost'`
- **Then**: Các email (nếu có) sẽ dùng FROM address này
- **Note**: Với dummy backend, setting này chỉ có ý nghĩa về mặt code

### REQ-EMAIL-007: Email Host Configuration (Optional)
- **Given**: Các cấu hình EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD
- **When**: Loại bỏ hoặc comment out các config này
- **Then**: Code sạch hơn, không có thông tin SMTP thừa
- **Note**: Với dummy backend, các config này không được sử dụng

## Verification

```bash
# Kiểm tra EMAIL_BACKEND
cd /home/thangdao/Documents/hoanggia.proj/code/zulip
python3 -c "
from django.conf import settings
print('EMAIL_BACKEND:', settings.EMAIL_BACKEND)
assert 'dummy' in settings.EMAIL_BACKEND.lower(), 'EMAIL_BACKEND not set to dummy!'
print('SUCCESS: Dummy email backend configured')
"

# Test gửi email (should do nothing)
python3 -c "
from django.core.mail import send_mail
result = send_mail('Test', 'Message', 'from@example.com', ['to@example.com'])
print('Send mail result (should be 0):', result)
print('SUCCESS: Email not sent (dummy backend)')
"
```

## Impact

- **Positive**: Đảm bảo không có email nào được gửi ra ngoài (ngay cả khi code cố gắng gửi)
- **Positive**: Không cần cấu hình SMTP
- **Negative**: Không gửi được email (expected)
