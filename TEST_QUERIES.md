# SQL Assistant — Test Queries & Memory Chat Guide

Use with `test_files/sample.db` (tables: `users`, `orders`, linked by `user_id`).

Upload the file first, then run these in order for a smooth demo — each
section builds on realistic complexity so you can stop wherever your time
runs out and still have a coherent test story.

---

## 1. Beginner

Basic reads. All should show a green **SAFE** badge.

```sql
SELECT * FROM users;
```
```sql
SELECT * FROM orders;
```
```sql
SELECT name, email FROM users;
```
```sql
SELECT * FROM users WHERE id = 1;
```
```sql
SELECT COUNT(*) FROM users;
```
```sql
SELECT * FROM orders ORDER BY amount DESC;
```
```sql
SELECT * FROM orders WHERE amount > 50;
```

---

## 2. Intermediate

Writes with a `WHERE` clause → yellow **CAUTION** badge. All roll back —
original data is untouched.

```sql
UPDATE users SET name = 'Alice Smith' WHERE id = 1;
```
```sql
INSERT INTO users (name, email) VALUES ('Dana', 'dana@x.com');
```
```sql
DELETE FROM orders WHERE amount < 20;
```
```sql
INSERT INTO orders (user_id, product, amount) VALUES (3, 'Chair', 89.99);
```

Aggregation / grouping:

```sql
SELECT user_id, COUNT(*) AS order_count
FROM orders
GROUP BY user_id;
```
```sql
SELECT user_id, SUM(amount) AS total_spent
FROM orders
GROUP BY user_id
HAVING SUM(amount) > 50;
```

---

## 3. Advanced

**Joins**
```sql
SELECT u.name, o.product, o.amount
FROM users u
JOIN orders o ON u.id = o.user_id;
```
```sql
SELECT u.name, o.product
FROM users u
LEFT JOIN orders o ON u.id = o.user_id;
```

**Subqueries**
```sql
SELECT name FROM users
WHERE id IN (SELECT user_id FROM orders WHERE amount > 100);
```

**CTE (WITH clause)**
```sql
WITH big_orders AS (
  SELECT * FROM orders WHERE amount > 50
)
SELECT u.name, b.product
FROM users u
JOIN big_orders b ON u.id = b.user_id;
```

**Schema-altering**
```sql
ALTER TABLE users ADD COLUMN phone TEXT;
```
```sql
CREATE INDEX idx_orders_user ON orders(user_id);
```

**Dangerous — should trigger red DANGER badge + pulse animation**
```sql
DELETE FROM users;
```
```sql
UPDATE orders SET amount = 0;
```
```sql
DROP TABLE orders;
```

**Error handling (should show a clean error, not a crash)**
```sql
SELECT * FROM nonexistent_table;
```
```sql
SELECT name, FROM users;
```

**Proof-of-safety sequence** — run these three in order to demonstrate
nothing is ever actually destroyed:
```sql
SELECT COUNT(*) FROM users;      -- note the count
DROP TABLE users;                 -- DANGER badge, rolled back
SELECT COUNT(*) FROM users;      -- same count as before, table still exists
```

---

## 4. Ask Memory — test questions

The chat box uses Gemini (if `GEMINI_API_KEY` is set in `.env`) with a
rule-based fallback if the key is missing or a call fails. Test both
paths if you can.

### Basic recall
```
what tables do you remember?
what did we do recently?
what happened last session?
summarize everything we've done so far
```

### Error recall
```
what errors have happened?
did any query fail?
```

### Query-specific recall
```
did I run any dangerous queries?
what queries touched the orders table?
have I joined users and orders before?
what was the riskiest query I ran?
```

### Schema reasoning (Gemini path shows the most value here — rule-based
fallback can't really answer these)
```
how are users and orders related?
which table would I need to query to find total spending per user?
is there a foreign key between these tables?
```

### Cross-session persistence test (the actual "no amnesia" proof)
1. Run a few queries above.
2. Ask: `what did we do recently?` — note the answer.
3. Stop the Flask server (`Ctrl+C`) and restart it (`python3 app.py`).
4. Reload the page — the same `project_id` is restored from
   `localStorage`, and memory is restored from `memory.json` on disk.
5. Ask the same question again — it should recall the same history from
   before the restart, proving memory persisted across the "session."

### Edge case / stress test
```
test
hello
asdkjfh
```
Should never crash — falls back to a generic summary of stored history
rather than erroring out.
