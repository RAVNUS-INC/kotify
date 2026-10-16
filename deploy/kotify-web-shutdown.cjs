// deploy/kotify-web-shutdown.cjs
//
// kotify-web.service 가 NODE_OPTIONS=--require 로 먼저 불러오는 종료 유예 처리.
//
// Next 14.2 standalone server.js 는 SIGTERM 에 server.close(() => process.exit(0)) 만
// 한다. 새 연결은 바로 거절하지만, 열린 요청이 끝날 때까지 프로세스가 남는다.
// 대화방 SSE(/api/chat/stream, rewrite 로 FastAPI 에 프록시)는 끝나지 않는 스트림이고,
// kotify-web 이 kotify 보다 먼저 정지하므로(After=kotify.service) FastAPI 쪽에서도
// 끊기지 않는다 → 대화방 탭이 하나라도 열려 있으면 TimeoutStopSec(기본 90초) 동안
// 새 연결이 거절되다가 SIGKILL 로 끝났다(2026-10-15·16 배포).
//
// 여기서는 SIGTERM 을 받으면 GRACE_MS 동안 Next 가 일반 요청을 마치도록 두고, 그때까지
// 남은 연결(SSE 등)이 있으면 끊고 정상 종료(0)한다. 열린 연결이 없으면 Next 의 close
// 콜백이 먼저 바로 종료한다. 끊긴 EventSource 는 프론트 백오프로 새 서버에 재연결한다.
//
// 운영에선 저장소 밖(/usr/local/lib/kotify/)에 복사해 쓴다 — git 롤백으로 이 파일이 없는
// 커밋이 체크아웃돼도 unit 이 가리키는 파일이 사라지지 않게(--require 대상이 없으면
// node 가 기동하지 못한다). 설치 방법은 deploy/README.md "kotify-web 종료 유예".

'use strict';

const DEFAULT_GRACE_MS = 5000;

function graceMs() {
    const raw = Number(process.env.KOTIFY_WEB_SHUTDOWN_GRACE_MS);
    return Number.isFinite(raw) && raw >= 0 ? raw : DEFAULT_GRACE_MS;
}

function onSigterm() {
    // NODE_OPTIONS 는 Next 가 띄우는 자식 node 에도 상속된다. 다른 SIGTERM 처리기가 없는
    // 프로세스(=Next 서버가 아닌 자식)는 리스너를 붙인 탓에 기본 동작(즉시 종료)을 잃었으므로
    // 리스너를 떼고 신호를 다시 보내 원래대로 끝낸다.
    if (process.listenerCount('SIGTERM') <= 1) {
        process.removeListener('SIGTERM', onSigterm);
        process.kill(process.pid, 'SIGTERM');
        return;
    }
    const ms = graceMs();
    console.log(`kotify-web: SIGTERM — 열린 요청을 최대 ${ms}ms 기다린 뒤 종료`);
    // unref: 열린 연결이 없으면 Next 의 close 콜백이 이 타이머를 기다리지 않고 끝낸다.
    setTimeout(() => {
        console.log('kotify-web: 종료 유예 만료 — 남은 연결(SSE 등)을 끊고 종료');
        process.exit(0);
    }, ms).unref();
}

process.on('SIGTERM', onSigterm);
