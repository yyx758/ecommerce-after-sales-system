USE ecommerce_aftersales;

SET FOREIGN_KEY_CHECKS = 0;
TRUNCATE TABLE ticket_log;
TRUNCATE TABLE ticket_attachment;
TRUNCATE TABLE after_sales_ticket;
TRUNCATE TABLE chat_message;
TRUNCATE TABLE chat_session;
TRUNCATE TABLE message_notice;
TRUNCATE TABLE order_item;
TRUNCATE TABLE order_info;
TRUNCATE TABLE product_info;
TRUNCATE TABLE sys_user;
TRUNCATE TABLE user_info;
SET FOREIGN_KEY_CHECKS = 1;

INSERT INTO user_info (id, user_account, phone, password, nickname, role_type, status) VALUES
(1, '13397987740', '13397987740', '$2a$10$N.zmdr9k7uOCQb376NoUnuTJ8iAt6Z5EHsM8lE9lBOsl7iKTVKIUi', 'yyx', 'USER', 1),
(2, '13072333340', '13072333340', '$2a$10$N.zmdr9k7uOCQb376NoUnuTJ8iAt6Z5EHsM8lE9lBOsl7iKTVKIUi', 'test_user_13072333340', 'USER', 1);

INSERT INTO sys_user (id, username, password, real_name, phone, email, role_type, status, online_status, max_sessions) VALUES
(1, 'cs_demo', '$2a$10$N.zmdr9k7uOCQb376NoUnuTJ8iAt6Z5EHsM8lE9lBOsl7iKTVKIUi', 'Demo Agent', '13800000001', 'cs_demo@example.com', 'AGENT', 1, 1, 8);

INSERT INTO product_info (id, product_name, product_code, category, description, main_image, images, price, status) VALUES
(1, 'Cotton T-Shirt', 'TSHIRT-001', 'CLOTHING', 'Basic cotton T-shirt for after-sales demo.', '/static/images/product-tshirt.png', '["/static/images/product-tshirt.png"]', 35.00, 1),
(2, 'Smart Phone', 'PHONE-001', 'DIGITAL', 'High-value phone used for quality issue demos.', '/static/images/product-phone.png', '["/static/images/product-phone.png"]', 2999.00, 1),
(3, 'Photo Paper', 'PHOTO-001', 'DAILY', 'Consumable product for shipping-status demos.', '/static/images/product-photo-paper.png', '["/static/images/product-photo-paper.png"]', 35.90, 1),
(4, 'Wireless Earphone', 'EARPHONE-001', 'DIGITAL', 'Bluetooth earphone used in purchase flow demos.', '/static/images/product-earphone.png', '["/static/images/product-earphone.png"]', 129.00, 1),
(5, 'Running Shoes', 'SHOE-001', 'SPORT', 'Running shoes used for logistics damage demos.', '/static/images/product-shoes.png', '["/static/images/product-shoes.png"]', 199.00, 1),
(6, 'Electric Kettle', 'KETTLE-001', 'HOME_APPLIANCE', 'Household electric kettle for normal purchase and after-sales scenarios.', '/static/images/product-photo-paper.png', '["/static/images/product-photo-paper.png"]', 89.00, 1);

INSERT INTO order_info (id, order_no, user_id, total_amount, pay_amount, status, receiver_name, receiver_phone, receiver_address, tracking_company, tracking_no, pay_time, ship_time, receive_time) VALUES
(1, 'ORD20240115001', 1, 35.00, 35.00, 'RECEIVED', 'yyx', '13397987740', 'Demo Address 19', 'SF', 'SF1234567890', '2024-01-15 14:30:00', '2024-01-16 09:00:00', '2024-01-18 14:00:00'),
(2, 'ORD20240118001', 1, 2999.00, 2999.00, 'RECEIVED', 'yyx', '13397987740', 'Demo Address 19', 'ZTO', 'ZT9876543210', '2024-01-18 10:00:00', '2024-01-19 08:00:00', '2024-01-21 16:00:00'),
(5, 'ORD20240125001', 1, 199.00, 199.00, 'RECEIVED', 'yyx', '13397987740', 'Demo Address 19', 'YD', 'YD6677889900', '2024-01-25 15:00:00', '2024-01-26 09:00:00', '2024-01-28 11:00:00'),
(6, 'ORD20240201001', 1, 89.00, 89.00, 'RECEIVED', 'yyx', '13397987740', 'Demo Address 19', 'SF', 'SF5566778899', '2024-02-01 09:00:00', '2024-02-01 12:00:00', '2024-02-03 18:00:00');

INSERT INTO order_info (id, order_no, user_id, total_amount, pay_amount, status, receiver_name, receiver_phone, receiver_address, tracking_company, tracking_no, pay_time, ship_time) VALUES
(3, 'ORD20240120001', 1, 35.90, 35.90, 'SHIPPED', 'yyx', '13397987740', 'Demo Address 19', 'YTO', 'YT1122334455', '2024-01-20 09:00:00', '2024-01-21 10:00:00');

INSERT INTO order_info (id, order_no, user_id, total_amount, pay_amount, status, receiver_name, receiver_phone, receiver_address, pay_time) VALUES
(4, 'ORD20240122001', 1, 328.00, 328.00, 'PAID', 'yyx', '13397987740', 'Demo Address 19', '2024-01-22 20:00:00');

INSERT INTO order_item (id, order_id, product_id, price, quantity, subtotal) VALUES
(1, 1, 1, 35.00, 1, 35.00),
(2, 2, 2, 2999.00, 1, 2999.00),
(3, 3, 3, 35.90, 1, 35.90),
(4, 4, 4, 129.00, 1, 129.00),
(5, 4, 5, 199.00, 1, 199.00),
(6, 5, 5, 199.00, 1, 199.00),
(7, 6, 6, 89.00, 1, 89.00);

INSERT INTO after_sales_ticket (id, ticket_no, order_id, order_no, user_id, product_name, reason, description, ai_recommend_type, status, priority) VALUES
(1, 'AS20240120001', 1, 'ORD20240115001', 1, 'Cotton T-Shirt', 'QUALITY', 'The collar opened after one use.', 'REFUND_RETURN', 'PROCESSING', 1);

INSERT INTO after_sales_ticket (id, ticket_no, order_id, order_no, user_id, product_name, after_sale_type, reason, description, ai_recommend_type, ai_confidence, status, priority, audit_opinion, audit_time) VALUES
(2, 'AS20240122001', 2, 'ORD20240118001', 1, 'Smart Phone', 'REFUND_RETURN', 'QUALITY', 'The screen has a visible scratch.', 'EXCHANGE', 0.85, 'APPROVED', 0, 'Approved for exchange after inspection.', '2024-01-23 10:00:00');

INSERT INTO after_sales_ticket (id, ticket_no, order_id, order_no, user_id, product_name, after_sale_type, reason, description, ai_recommend_type, ai_confidence, status, priority, refund_amount, audit_opinion, audit_time, complete_time) VALUES
(3, 'AS20240125001', 5, 'ORD20240125001', 1, 'Running Shoes', 'REFUND_ONLY', 'DAMAGE', 'The package and shoes were damaged on arrival.', 'REFUND_ONLY', 0.95, 'COMPLETED', 1, 199.00, 'Confirmed logistics damage and refunded in full.', '2024-01-26 09:00:00', '2024-01-27 14:00:00');

INSERT INTO ticket_attachment (id, ticket_id, file_url, file_type, file_name, sort_order) VALUES
(1, 1, '/static/images/product-tshirt.png', 'IMAGE', 'tshirt.jpg', 0),
(3, 3, '/static/images/product-shoes.png', 'IMAGE', 'shoes.jpg', 0);

INSERT INTO ticket_log (id, ticket_id, operator_id, operator_type, from_status, to_status, action, content) VALUES
(1, 1, NULL, 'USER', NULL, 'PENDING', 'SUBMIT', 'User submitted an after-sales request.'),
(2, 1, NULL, 'AI', 'PENDING', 'PROCESSING', 'AI_CLASSIFY', 'AI classified the issue as a quality problem.'),
(3, 2, NULL, 'USER', NULL, 'PENDING', 'SUBMIT', 'User submitted an after-sales request.'),
(4, 2, NULL, 'AI', 'PENDING', 'PROCESSING', 'AI_CLASSIFY', 'AI recommended exchange.'),
(5, 2, 1, 'AGENT', 'PROCESSING', 'APPROVED', 'APPROVE', 'Agent approved the exchange request.'),
(6, 3, NULL, 'USER', NULL, 'PENDING', 'SUBMIT', 'User submitted an after-sales request.'),
(7, 3, NULL, 'AI', 'PENDING', 'PROCESSING', 'AI_CLASSIFY', 'AI recognized logistics damage.'),
(8, 3, 1, 'AGENT', 'PROCESSING', 'APPROVED', 'APPROVE', 'Agent approved the refund request.'),
(9, 3, NULL, 'SYSTEM', 'APPROVED', 'COMPLETED', 'AUTO_REFUND', 'System completed the refund.');

INSERT INTO chat_session (id, session_no, user_id, order_id, ticket_id, human_agent_id, mode, status, emotion_score, emotion_label, user_query, resolved, satisfaction) VALUES
(101, 'CS20260625007', 1, 1, 1, 1, 'HUMAN', 'ACTIVE', 0.35, 'ANXIETY', 'When will the refund arrive?', 0, NULL),
(102, 'CS20260625008', 1, 2, 2, 1, 'HUMAN', 'WAITING', 0.55, 'NORMAL', 'Exchange logistics is not updating.', 0, NULL),
(103, 'CS20260625009', 1, 5, 3, 1, 'HUMAN', 'CLOSED', 0.90, 'NORMAL', 'Service review completed.', 1, 5);

INSERT INTO chat_message (id, session_id, role, content, message_type, emotion_label) VALUES
(1, 101, 'USER', 'When will my refund be credited?', 'TEXT', 'ANXIETY'),
(2, 101, 'ASSISTANT', 'Your refund request is still being processed.', 'TEXT', 'NORMAL'),
(3, 102, 'USER', 'There has been no logistics update for three days.', 'TEXT', 'NORMAL'),
(4, 103, 'SYSTEM', 'The user has completed the service rating.', 'TEXT', 'NORMAL');

INSERT INTO message_notice (id, user_id, title, content, notice_type, ref_id, ref_type, is_read) VALUES
(1, 1, 'Refund ticket pending review', 'AS20240120001 needs follow-up processing.', 'AFTER_SALE', 1, 'TICKET', 0),
(2, 1, 'New session waiting', 'CS20260625008 is waiting for support access.', 'CHAT', 102, 'SESSION', 0),
(3, 1, 'Order linked update', 'ORD20240118001 after-sales status has been updated.', 'ORDER', 2, 'ORDER', 1);
