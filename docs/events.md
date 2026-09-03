
# Event Bus — Event Names (Redis Streams, Kafka-ready)

## Commerce Events
- cart.created {cart_id, merchant_id, customer_id}
- cart.item_added {cart_id, product_id, quantity}
- cart.item_removed {cart_id, product_id}
- order.created {order_id, checkout_id, merchant_id}
- order.paid {order_id, payment_id}
- order.failed {order_id, reason}

## Payment Events
- payment.created {payment_id, order_id, amount}
- payment.captured {payment_id, razorpay_payment_id}
- payment.failed {payment_id, reason}
- webhook.received {event_id, type, payload}
- webhook.deduped {event_id}
- webhook.duplicate_ignored {event_id}

## Agent Events
- agent.session_started {session_id}
- agent.tool_called {session_id, tool, input}
- agent.policy_checked {session_id, decision, reason}
- agent.action_audited {audit_event_id}

## Intelligence Events
- recommendation.generated {customer_id, product_id, reason, score}
- cross_sell.proposed {cart_id, recommended_product_id, affinity_score}

## System Events
- policy.updated {merchant_id}
- inventory.updated {product_id, stock}

Channel naming: merchant:{merchant_id}:events  or global:events for hackathon
Consumer groups: order-service, audit-service, analytics, notification
Idempotency: webhook_event_id + payment_attempt_id dedup tables
