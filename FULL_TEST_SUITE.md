# SQL Assistant — Full Test Suite

Test database: `test_files/sample.db`

```
users  (id, name, email)
  1  Alice    a@x.com
  2  Bob      b@x.com
  3  Charlie  c@x.com

orders (id, user_id, product, amount)
  1  1  Keyboard   49.99
  2  1  Mouse      19.99
  3  2  Monitor   199.99
  4  3  Desk      149.99
  5  2  Webcam     39.99
```

Every query in this file is written as: **query → expected risk badge →
expected result**, so you can run it and immediately tell pass/fail rather
than guessing. Because every write executes inside `BEGIN ... ROLLBACK`,
re-running the SELECT checks below the writes should always show the
original, unmodified data.

---

## 1. Beginner reads — expect SAFE

| Query | Expected result |
|---|---|
| `SELECT * FROM users;` | 3 rows |
| `SELECT * FROM orders;` | 5 rows |
| `SELECT name, email FROM users;` | 3 rows, 2 columns |
| `SELECT * FROM users WHERE id = 2;` | 1 row (Bob) |
| `SELECT COUNT(*) FROM orders;` | `5` |
| `SELECT * FROM orders WHERE amount > 100;` | 2 rows (Monitor, Desk) |
| `SELECT DISTINCT user_id FROM orders;` | `1, 2, 3` |

```sql
SELECT * FROM users;
SELECT * FROM orders;
SELECT name, email FROM users;
SELECT * FROM users WHERE id = 2;
SELECT COUNT(*) FROM orders;
SELECT * FROM orders WHERE amount > 100;
SELECT DISTINCT user_id FROM orders;
```

---

## 2. Intermediate — aggregation, grouping — expect SAFE

```sql
SELECT user_id, COUNT(*) AS order_count
FROM orders
GROUP BY user_id;
```
Expected: user 1 → 2, user 2 → 2, user 3 → 1

```sql
SELECT user_id, SUM(amount) AS total_spent
FROM orders
GROUP BY user_id
ORDER BY total_spent DESC;
```
Expected: user 2 → 239.98, user 3 → 149.99, user 1 → 69.98

```sql
SELECT user_id, AVG(amount) AS avg_order
FROM orders
GROUP BY user_id
HAVING AVG(amount) > 50;
```
Expected: only user 2 (avg ~119.99) and user 3 (149.99) — user 1's avg (34.99) excluded

---

## 3. Strong JOINs — expect SAFE

**Basic inner join**
```sql
SELECT u.name, o.product, o.amount
FROM users u
JOIN orders o ON u.id = o.user_id;
```
Expected: 5 rows, every order paired with its owner's name.

**Left join — reveals users with no orders**
First add a user with no orders, then test the join in the same query
using a CTE so it doesn't require a real INSERT:
```sql
WITH all_users AS (
  SELECT * FROM users
  UNION ALL
  SELECT 99, 'NoOrders', 'noorders@x.com'
)
SELECT u.name, o.product
FROM all_users u
LEFT JOIN orders o ON u.id = o.user_id;
```
Expected: 6 rows total; `NoOrders` shows with `NULL` product — proves LEFT JOIN keeps unmatched rows.

**Join + aggregate together**
```sql
SELECT u.name, COUNT(o.id) AS num_orders, SUM(o.amount) AS total
FROM users u
JOIN orders o ON u.id = o.user_id
GROUP BY u.name
ORDER BY total DESC;
```
Expected: Bob (2 orders, 239.98), Charlie (1 order, 149.99), Alice (2 orders, 69.98)

**Self-referencing style join using a subquery (finds users who spent above the average order amount)**
```sql
SELECT u.name, o.product, o.amount
FROM users u
JOIN orders o ON u.id = o.user_id
WHERE o.amount > (SELECT AVG(amount) FROM orders);
```
Expected: only orders above ~91.99 avg → Monitor (Bob), Desk (Charlie)

**Multi-condition join**
```sql
SELECT u.name, o.product
FROM users u
JOIN orders o ON u.id = o.user_id AND o.amount > 40;
```
Expected: Keyboard (Alice), Monitor (Bob), Desk (Charlie), Webcam (Bob) — Mouse (19.99) excluded

**Correlated subquery — each user's most expensive order**
```sql
SELECT u.name, o.product, o.amount
FROM users u
JOIN orders o ON u.id = o.user_id
WHERE o.amount = (
  SELECT MAX(amount) FROM orders WHERE user_id = u.id
);
```
Expected: Alice/Keyboard, Bob/Monitor, Charlie/Desk

---

## 4. Strong DELETEs — mixed risk levels

**Safe-ish delete — has WHERE, still flagged CAUTION (any write is)**
```sql
DELETE FROM orders WHERE amount < 20;
```
Expected: CAUTION badge, 1 row affected (Mouse), rolled back — re-run
`SELECT COUNT(*) FROM orders;` afterward to confirm it's still 5.

**Delete using a subquery condition**
```sql
DELETE FROM orders
WHERE user_id IN (SELECT id FROM users WHERE name = 'Bob');
```
Expected: CAUTION, 2 rows affected (Monitor, Webcam), rolled back.

**Delete using EXISTS (join-like delete)**
```sql
DELETE FROM orders
WHERE EXISTS (
  SELECT 1 FROM users u WHERE u.id = orders.user_id AND u.name = 'Charlie'
);
```
Expected: CAUTION, 1 row affected (Desk), rolled back.

**Delete with no WHERE — expect DANGER**
```sql
DELETE FROM orders;
```
Expected: red DANGER badge, "affects all rows" reason, 5 rows affected, rolled back.

```sql
DELETE FROM users;
```
Expected: red DANGER badge, 3 rows affected, rolled back.

**Chained dangerous deletes across both tables (run back to back)**
```sql
DELETE FROM orders;
```
```sql
DELETE FROM users;
```
Then immediately verify nothing was actually lost:
```sql
SELECT COUNT(*) FROM users;
SELECT COUNT(*) FROM orders;
```
Expected: `3` and `5` — proving both deletes were rolled back independently.

---

## 5. Other writes — expect CAUTION or DANGER

```sql
UPDATE users SET name = 'Alice Smith' WHERE id = 1;
```
Expected: CAUTION, 1 row affected, rolled back.

```sql
UPDATE orders SET amount = 0;
```
Expected: DANGER (UPDATE with no WHERE), 5 rows affected, rolled back.

```sql
INSERT INTO orders (user_id, product, amount) VALUES (3, 'Chair', 89.99);
```
Expected: CAUTION (or safe-write, depending on your classifier), 1 row
inserted — confirm with `SELECT COUNT(*) FROM orders;` still shows 5 after.

```sql
ALTER TABLE users ADD COLUMN phone TEXT;
```
Expected: schema-altering write, at minimum CAUTION.

```sql
DROP TABLE orders;
```
Expected: DANGER, and orders table must still exist afterward —
confirm with `SELECT COUNT(*) FROM orders;`.

---

## 6. Error handling — expect a clean error, not a crash

```sql
SELECT * FROM nonexistent_table;
```
Expected: error message returned in JSON, app does not crash, error is
logged to memory.

```sql
SELECT name, FROM users;
```
Expected: SQL syntax error surfaced cleanly.

```sql
SELECT * FROM users WHERE id = 'not_a_number';
```
Expected: either an empty result (SQLite is loosely typed) or a clean
error — should not crash the server either way.

---

## 7. Ask Memory — full persistence test protocol

The chat endpoint calls Gemini if `GEMINI_API_KEY` is set in `.env`;
otherwise it falls back to rule-based answers. Response JSON includes
`"source": "gemini"` or `"source": "fallback"` — check this in your
browser's Network tab to confirm which path answered.

### Step-by-step protocol

**Step 1 — Build up history.** Run at least these three queries first:
```sql
SELECT * FROM users;
DELETE FROM orders;
SELECT * FROM nonexistent_table;
```
(a safe read, a dangerous delete, and an error — one of each memory type)

**Step 2 — Ask these and confirm each answer references real history:**
```
what did we do recently?
```
Expected: mentions the upload, the SELECT, the DELETE, and the error — in order.

```
what errors have happened?
```
Expected: specifically mentions `nonexistent_table`.

```
did I run any dangerous queries?
```
Expected: mentions the `DELETE FROM orders` as high-risk. (Gemini path
answers this well; rule-based fallback may only give a generic count —
note which one you got.)

```
what tables do you remember?
```
Expected: `users, orders`.

**Step 3 — Restart the server** (kill and re-run `python3 app.py`).
This proves memory is not just in-process — it's read from `memory.json`
on disk, simulating a brand-new session.

**Step 4 — Reload the browser page.** `project_id` is restored from
`localStorage`, so you don't need to re-upload.

**Step 5 — Ask again:**
```
what did we do last session?
```
Expected: same history as Step 2, proving it survived the restart.
**This is the core "no amnesia" proof for your demo — don't skip it.**

### Stress / edge-case questions
```
test
hello
asdkjfh
```
Expected: never crashes; falls back to a generic summary
("this project has N queries and M errors...") instead of erroring.

```
what tables exist in a database I never uploaded?
```
Expected (new/unused project_id): "I don't have any memory for this project yet."

---

## 8. Quick pass/fail checklist

- [ ] All SELECTs return correct rows/counts
- [ ] Every write is followed by a verifying SELECT showing no real change
- [ ] DELETE/UPDATE without WHERE shows DANGER badge with pulse animation
- [ ] DROP TABLE shows DANGER, table still queryable afterward
- [ ] Malformed SQL returns a clean error, server stays up
- [ ] Chat correctly recalls recent activity, errors, and tables
- [ ] Chat survives a full server restart with the same answers
- [ ] Chat never crashes on nonsense input
- [ ] `source` field shows `gemini` when a valid key is set, `fallback` otherwise
