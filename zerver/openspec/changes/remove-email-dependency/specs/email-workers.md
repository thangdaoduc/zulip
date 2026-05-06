# Spec: Email Worker Disabling

## Summary

Disable tất cả email workers để ngừng xử lý email queues.

## Requirements

### REQ-EMAIL-001: EmailSendingWorker Disabled
- **Given**: Hệ thống Zulip với EmailSendingWorker
- **When**: Cấu hình `enabled=False` trong `@assign_queue` decorator
- **Then**: Worker không được register vào `worker_classes`
- **Then**: Queue `email_senders` không được consume

### REQ-EMAIL-002: MissedMessageWorker Disabled
- **Given**: Hệ thống Zulip với MissedMessageWorker (xử lý batched email notifications)
- **When**: Cấu hình `enabled=False` trong `@assign_queue` decorator
- **Then**: Worker không được register
- **Then**: Queue `missedmessage_emails` không được consume
- **Note**: ScheduledMessageNotificationEmail records sẽ không được xử lý (không ảnh hưởng vì notification đã tắt)

### REQ-EMAIL-003: DigestWorker Disabled
- **Given**: Hệ thống Zulip với DigestWorker (gửi digest emails hàng ngày)
- **When**: Cấu hình `enabled=False` trong `@assign_queue` decorator
- **Then**: Worker không được register
- **Then**: Queue `digest_emails` không được consume

### REQ-EMAIL-004: DeferredEmailWorker Check
- **Given**: Hệ thống Zulip có thể có DeferredEmailWorker
- **When**: Kiểm tra file `zerver/worker/deferred_email_senders.py`
- **If exists**: Disable bằng `enabled=False`
- **Then**: Queue `deferred_email_senders` không được consume

## Verification

```bash
# Kiểm tra workers không được load
cd /home/thangdao/Documents/hoanggia.proj/code/zulip
python3 -c "
from zerver.worker.queue_processors import get_active_worker_queues
queues = get_active_worker_queues()
email_queues = [q for q in queues if 'email' in q.lower()]
print('Email queues still active:', email_queues)
assert len(email_queues) == 0, 'Email workers still enabled!'
print('SUCCESS: All email workers disabled')
"
```

## Impact

- **Positive**: Giảm tài nguyên (CPU, memory) cho workers
- **Positive**: Không cần SMTP connection
- **Negative**: Không gửi được email (expected behavior)
