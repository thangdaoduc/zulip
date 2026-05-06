# Proposal: Remove Email Dependency

## Summary

Loại bỏ hoàn toàn sự phụ thuộc vào email trong bản fork Zulip, bao gồm:
- Tắt các email workers
- Cấu hình dummy email backend
- Vô hiệu hóa email notifications mặc định
- Giữ nguyên cấu trúc UserProfile với fake email

## Motivation

Bản fork Zulip không cần sử dụng email, việc giữ lại các tính năng email:
- Lãng phí tài nguyên (workers, queues)
- Gây phức tạp không cần thiết
- Có thể gây lỗi nếu cấu hình SMTP không đúng

## Scope

### In Scope
- Tắt 4 email workers chính
- Cấu hình EMAIL_BACKEND = dummy
- Tắt email notifications mặc định cho user mới
- Đảm bảo fake email vẫn hoạt động (user1234@realm)

### Out of Scope
- Thay đổi USERNAME_FIELD từ "email" sang "username" (quá phức tạp)
- Xóa bỏ hoàn toàn các trường email trong database (cần migration phức tạp)
- Loại bỏ Gravatar (vẫn dùng Jdenticon làm mặc định)

## Success Criteria

1. Không có email workers nào được khởi động khi chạy `./manage.py runworker`
2. Email notifications được tắt mặc định cho user mới
3. Hệ thống vẫn hoạt động bình thường với fake email
4. Password reset và invitation cần dùng phương thức khác (không email)

## Risks

- **Medium**: Password reset sẽ không gửi được email → Cần admin reset thủ công
- **Medium**: Invitation email sẽ không gửi → Cần dùng invitation link trực tiếp
- **Low**: Một số tính năng liên quan đến email trong code sẽ không hoạt động → Đã tắt workers nên không ảnh hưởng

## Alternatives Considered

1. **Xóa hoàn toàn email fields**: Quá phức tạp, cần migration lớn, ảnh hưởng đến Django auth
2. **Giữ nguyên và cấu hình SMTP rỗng**: Vẫn tốn tài nguyên chạy workers
3. **Proposal hiện tại (tắt workers + dummy backend)**: Cân bằng giữa đơn giản và hiệu quả

## Timeline

- Thực hiện: 1-2 giờ
- Test: 30 phút
- Rollback: 5 phút (git revert)
