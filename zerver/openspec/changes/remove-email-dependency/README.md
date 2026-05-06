# Remove Email Dependency - Summary

## 📋 Overview

Đây là proposal để loại bỏ hoàn toàn sự phụ thuộc vào email trong bản fork Zulip, bao gồm:
- Tắt 4 email workers chính
- Cấu hình dummy email backend
- Vô hiệu hóa email notifications mặc định
- Giữ nguyên cấu trúc UserProfile (dùng fake email)

## 🎯 Key Decisions

1. **Không xóa email fields** - Giữ `delivery_email` và `email` trong UserProfile, dùng fake email (user1234@realm)
2. **Tắt workers thay vì xóa code** - Đơn giản, dễ rollback, không ảnh hưởng đến logic khác
3. **Dùng dummy backend** - Đảm bảo mọi code cố gắng gửi email sẽ không làm gì cả (no-op)

## 📂 Artifacts Created

```
zerver/openspec/changes/remove-email-dependency/
├── proposal.md              # Tổng quan, motivation, scope, risks
├── design.md                # Kiến trúc chi tiết, technical approach
├── tasks.md                 # Danh sách tasks chi tiết, có thể check-off
└── specs/
    ├── email-workers.md     # Spec cho worker disabling
    ├── email-backend.md     # Spec cho dummy backend config
    └── user-settings.md    # Spec cho default user settings
```

## ⚡ Quick Implementation

### Files to Modify (4 workers):
1. `zerver/worker/email_senders_base.py` - Line 47: Thêm `enabled=False`
2. `zerver/worker/missedmessage_emails.py` - Line 25: Thêm `enabled=False`
3. `zerver/worker/digest_emails.py` - Line 14: Thêm `enabled=False`
4. `zerver/worker/deferred_email_senders.py` - Kiểm tra và thêm `enabled=False`

### Settings to Add (in `zproject/settings.py` or `computed_settings.py`):
```python
EMAIL_BACKEND = 'django.core.mail.backends.dummy.EmailBackend'
DEFAULT_FROM_EMAIL = 'noreply@localhost'
SERVER_EMAIL = 'noreply@localhost'

USER_SETTINGS_DEFAULT_OVERRIDES = {
    'enable_offline_email_notifications': False,
    'enable_followed_topic_email_notifications': False,
    'enable_stream_email_notifications': False,
    'enable_digest_emails': False,
    'enable_login_emails': False,
    'enable_marketing_emails': False,
}
```

## ✅ Verification

Sau khi implement, chạy:
```bash
# Kiểm tra workers
./manage.py runworker --list | grep -i email  # Should return nothing

# Kiểm tra backend
./manage.py shell -c "from django.conf import settings; print(settings.EMAIL_BACKEND)"

# Kiểm tra user defaults
./manage.py shell -c "from zerver.models import RealmUserDefault; print(RealmUserDefault.objects.first().enable_offline_email_notifications)"
```

## ⚠️ Known Limitations

- **Password reset**: Không gửi được email → Admin cần reset thủ công hoặc dùng phương thức khác
- **Invitations**: Không gửi được invitation email → Dùng invitation link trực tiếp
- **USERNAME_FIELD**: Vẫn là "email" (dùng fake email) → Không đổi sang username vì quá phức tạp

## 🔄 Rollback

Nếu cần quay lại:
```bash
git revert <commit-hash>
# Hoặc
git checkout HEAD~1 -- zerver/worker/ zproject/settings.py
```

## 📊 Effort Estimate

- **Implementation**: 1-2 giờ
- **Testing**: 30 phút
- **Total**: ~2.5 giờ

## 🚀 Next Steps

1. Review proposal và design
2. Implement theo tasks.md
3. Test kỹ trên staging
4. Deploy lên production
5. Monitor để đảm bảo không có issues
