-- Патч триггера аудита оценок (применять один раз к базе):
--   psql -U postgres -d portal_new -f patch_audit_trigger.sql
--
-- Зачем: без патча триггер пишет в grade_audit_log строку БЕЗ причины, а бэкенд
-- (который требует причину при изменении оценки) пишет вторую строку: в истории дубль.
-- С патчем триггер сам берёт причину и автора из настроек транзакции, дубля нет.
-- Без патча бэкенд работает, просто с дублями.
CREATE OR REPLACE FUNCTION log_grade_change() RETURNS TRIGGER AS $$
DECLARE
    v_reason text := NULLIF(current_setting('app.reason', true), '');
    v_user   int  := NULLIF(current_setting('app.user_id', true), '')::int;
BEGIN
    IF TG_OP = 'INSERT' OR OLD.score IS DISTINCT FROM NEW.score OR OLD.status IS DISTINCT FROM NEW.status THEN
        INSERT INTO grade_audit_log (grade_id, changed_by, old_score, new_score, old_status, new_status, reason)
        VALUES (NEW.id,
                COALESCE(v_user, NEW.graded_by, (SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1)),
                CASE WHEN TG_OP = 'UPDATE' THEN OLD.score END, NEW.score,
                CASE WHEN TG_OP = 'UPDATE' THEN OLD.status END, NEW.status,
                v_reason);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
