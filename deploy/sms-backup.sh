#!/usr/bin/env bash
# deploy/sms-backup.sh
# SQLite DB 일일 백업 스크립트
# 실행 계정: sms (cron에서 자동 실행)
# 실행 시각: 매일 00:00 (sms-backup.cron 참고)
#
# 주의: master.key는 의도적으로 백업하지 않습니다.
#       master.key는 별도 안전한 위치(1Password, 사내 비밀 저장소)에 수동 보관하세요.
#       master.key + DB 백업이 같은 장소에 있으면 암호화 의미가 없습니다.

set -euo pipefail

# ── 설정 ─────────────────────────────────────────────────────────────────────
DB_SOURCE="/var/lib/sms/sms.db"
BACKUP_DIR="/var/backups/sms"
RETENTION_DAYS=30
TIMESTAMP=$(date +%Y%m%d)
BACKUP_FILE="${BACKUP_DIR}/sms-${TIMESTAMP}.db"
LOG_TAG="sms-backup"

# ── 함수 ─────────────────────────────────────────────────────────────────────
log_info() {
    logger -t "${LOG_TAG}" -p user.info "$*"
}

log_error() {
    logger -t "${LOG_TAG}" -p user.err "$*"
}

# ── DB 존재 확인 ─────────────────────────────────────────────────────────────
if [[ ! -f "${DB_SOURCE}" ]]; then
    log_error "DB 파일 없음: ${DB_SOURCE}"
    exit 1
fi

# ── 백업 디렉토리 확인 ───────────────────────────────────────────────────────
if [[ ! -d "${BACKUP_DIR}" ]]; then
    log_error "백업 디렉토리 없음: ${BACKUP_DIR}"
    exit 1
fi

# ── SQLite .backup API로 안전하게 복사 ──────────────────────────────────────
# WAL 모드에서 운영 중인 DB도 데이터 손상 없이 복사합니다.
# (cp 명령은 WAL 저널 중간에 복사하면 손상 위험이 있음)
if sqlite3 "${DB_SOURCE}" ".backup '${BACKUP_FILE}'"; then
    BACKUP_SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
    log_info "백업 성공: ${BACKUP_FILE} (${BACKUP_SIZE})"
else
    log_error "백업 실패: sqlite3 .backup 오류"
    # 실패한 불완전한 파일이 있으면 삭제
    [[ -f "${BACKUP_FILE}" ]] && rm -f "${BACKUP_FILE}"
    exit 1
fi

# ── 30일 이상 된 백업 자동 삭제 ─────────────────────────────────────────────
DELETED_COUNT=0
while IFS= read -r old_file; do
    rm -f "${old_file}"
    DELETED_COUNT=$((DELETED_COUNT + 1))
    log_info "오래된 백업 삭제: ${old_file}"
done < <(find "${BACKUP_DIR}" -name "sms-*.db" -mtime "+${RETENTION_DAYS}" -type f)

if [[ ${DELETED_COUNT} -gt 0 ]]; then
    log_info "${DELETED_COUNT}개의 오래된 백업 파일 삭제 완료"
fi

log_info "백업 완료. 보관 중인 백업 수: $(find "${BACKUP_DIR}" -name "sms-*.db" -type f | wc -l)"
