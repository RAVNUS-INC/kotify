# 3.2 컨텐츠(이미지) 관리
> 원문: https://doc.msghub.uplus.co.kr/rest-api/03채널/0302mnt-contents/ · 확인일 2026-10-16

메시지 발송에 쓸 이미지·파일을 채널별로 등록하고(업로드), 등록한 컨텐츠를 조회한다. 모두 `mnt-api` 호스트이며 Bearer 토큰이 필요하다(인증은 10-mnt-auth.md).

## 한눈에 보기

| 기능 | Method | 경로 | 호스트 |
|---|---|---|---|
| 파일 업로드 | POST | `/file/v1/{ch}` | mnt-api |
| 컨텐츠 조회 | GET | `/contents/v1/{apiKey}/{ch}/{fileId}` | mnt-api |

## 파일 업로드

`POST /file/v1/{ch}` — multipart/form-data 로 이미지를 등록하고 채널별 이미지 URL·만료일시를 받는다.

Header

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| Authorization | String | ● | `Bearer {token}` |
| Content-Type | String | ● | `multipart/form-data` |

Path

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| ch | String | ● | 채널: `mms` / `rcs` / `friendtalk` / `brandtalk` / `push` / `rbc` / `rbc_bia` |

`ch` 값별 용도 (원문에 설명된 것만)

| ch | 용도 |
|---|---|
| rbc | RBC 메시지베이스 이미지 등록 |
| rbc_bia | RBC 자동응답메시지 이미지 등록 |
| rcs | 템플릿이 아닌 RCS 발송용 이미지 등록 |
| brandtalk | 이미지형·비디오형 썸네일·커머스형의 `imgType` 은 `IMAGE` |

Body (multipart 필드 2개)

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| reqFile | Object(JSON 문자열) | ● | 파일 요청 정보. 아래 표 |
| filePart | File(Array) | ● | 업로드할 파일. curl 에서는 `-F "filePart=@100.jpg;type=image/jpeg"` |

reqFile 객체

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| fileId | String | ● | - | 파일 ID. 고유값이며 이미 등록된 ID 는 쓸 수 없다 |
| imgType | String | ● | - | 템플릿 유형. 브랜드톡이면 필수. `IMAGE`, `WIDE`, `WIDE_ITEM_LIST`, `CAROUSEL_FEED`, `CAROUSEL_COMMERCE` |
| kkoItemListFirstYn | String | - | - | 브랜드톡 와이드 아이템리스트의 첫 번째 이미지 여부(Y/N). 브랜드톡이면 필수라고 원문에 적혀 있으나 필수 표시는 `-` |
| wideYn | String | - | - | 카카오 와이드 이미지 여부(Y/N) |
| kkoItemListYn | String | - | - | 카카오 아이템리스트 여부(Y/N) |
| kkoCarouselFeedYn | String | - | - | 카카오 캐러셀 피드 여부(Y/N) |
| kkoCarouselCommerceYn | String | - | - | 카카오 캐러셀 커머스 여부(Y/N) |
| brandId | String | - | - | RCS 브랜드 ID |

응답 data

| 필드 | 타입 | 설명 |
|---|---|---|
| ch | String | 채널 |
| imgUrl | String | 이미지 URL(카카오) |
| imgUrlLst | Array | 이미지 URL 목록(카카오) |
| fileId | String | 파일 ID |
| fileExpDt | String | 파일 만료일시(`yyyy-MM-ddTHH:mm:ss`) |

예시

```bash
curl -X POST "https://mnt-api.msghub.uplus.co.kr/file/v1/brandtalk" \
  -H "Authorization: Bearer {token}" \
  -F 'reqFile={"fileId":"my_image_01","imgType":"WIDE_ITEM_LIST","kkoItemListFirstYn":"Y","wideYn":"N","kkoItemListYn":"N","kkoCarouselFeedYn":"N","kkoCarouselCommerceYn":"N"}' \
  -F "filePart=@100.jpg;type=image/jpeg"
```

```json
{
  "code": "10000",
  "message": "성공",
  "data": {
    "ch": "brandtalk",
    "imgUrl": "https://mud-kage.kakao.com/dn/.../img.jpg",
    "imgUrlLst": ["https://mud-kage.kakao.com/dn/.../img.jpg"],
    "fileId": "my_image_01",
    "fileExpDt": "2026-07-09T09:48:35"
  }
}
```

> 주의
> - `fileId` 는 중복될 수 없다. 이미 등록된 ID 로 올리면 실패한다.
> - 파일 크기·형식은 채널별 제한(아래 [채널별 이미지 규격](#채널별-이미지-규격))을 지켜야 한다.
> - 등록된 파일에는 유효기간이 있고 만료되면 다시 등록해야 한다. 기간은 응답 `fileExpDt` 로만 알 수 있으며 일수는 원문에 없다. 원문 확인 필요: 파일 ID 유효기간(채널별 일수).
> - 원문 확인 필요: `friendtalk`·`push`·`rbc`·`rbc_bia` 채널의 형식·크기 제한과 `filePart` 에 한 번에 올릴 수 있는 파일 수(타입이 Array 로 적혀 있음). Appendix 에는 MMS·RCS·브랜드톡·푸시만 있다.
> - 원문 확인 필요: 응답에서 `imgUrl`/`imgUrlLst` 는 카카오 용으로만 표기되어 있어 mms·rcs 등은 응답 형태가 다를 수 있다.

## 컨텐츠 조회

`GET /contents/v1/{apiKey}/{ch}/{fileId}` — 등록한 파일을 조회한다. 성공하면 JSON 이 아니라 파일 바이너리를 응답 본문으로 돌려준다.

Header

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| Authorization | String | ● | `Bearer {token}` |

Path

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| apiKey | String | ● | API 키 |
| ch | String | ● | 채널(원문 표기: `mms`) |
| fileId | String | ● | 파일 ID |

성공 응답: 본문은 파일의 바이너리 데이터, 헤더는 아래와 같다.

| 헤더 | 설명 | 예시 |
|---|---|---|
| Content-Type | 파일 유형의 MIME 타입 | `image/jpeg` |
| Content-Disposition | 파일 처리 정보 | `inline; filename="FL…ERJ.jpg"` |
| Content-Length | 파일 크기(바이트) | `7922` |

실패 응답 예시

```json
{ "code": "29009", "message": "요청한 데이터 없음" }
```

예시

```bash
curl -X GET "https://mnt-api.msghub.uplus.co.kr/contents/v1/{apiKey}/mms/{fileId}" \
  -H "Authorization: Bearer {token}"
```

> 주의
> - 만료된 파일은 조회할 수 없다.
> - 원문 주의사항에는 "파일 데이터는 base64로 인코딩되어 반환된다"고 적혀 있으나, 같은 문서의 성공 응답 예시는 바이너리 본문이다. 원문 확인 필요: 실제 응답 인코딩.
> - 원문 확인 필요: `ch` 에 `mms` 외 값을 쓸 수 있는지.

## 채널별 이미지 규격

### MMS

| 항목 | 값 |
|---|---|
| 지원 형식 | JPG, JPEG, GIF (GIF 는 첫 프레임만 사용) |
| 파일 크기 | 최대 300KB |
| 사이즈 | 최대 1500×1440px |

### RCS

공통: 지원 형식 JPG, JPEG, PNG, BMP, GIF / 파일 크기 최대 1MB.

| 유형 | 사이즈 |
|---|---|
| 이미지형(세로형) | 568×336px (권장) |
| 이미지형(이미지 강조) | 900×900px 또는 900×1200px (필수) |
| 썸네일형 | 이미지 900×560px (필수), 썸네일 이미지 300×300px (필수) |
| SNS형 | 900×900px (필수) |
| SNS형(중간버튼) | 900×560px (필수) |
| 슬라이드형(Small) | 360×336px (권장) / 360×1620px (최대) |
| 슬라이드형(Medium) | 696×504px (권장) / 696×1620px (최대) |

### 카카오 브랜드톡

공통: 지원 형식 JPG, JPEG, PNG / 파일 크기 최대 5MB / 가로 500px 이상.

| 유형 | 가로:세로 비율 | 권장 사이즈 |
|---|---|---|
| 이미지형, 커머스형, 캐러셀 피드형, 프리미엄 동영상 썸네일 | 2:1 이상 3:4 이하 | 800×400, 800×600 |
| 와이드형 | 2:1 이상 1:1 이하 | 800×600 |
| 와이드 리스트형 첫 번째 이미지 | 2:1 | - |
| 와이드 리스트형 2~4번째 이미지 | 1:1 | - |
| 캐러셀 커머스형 | 2:1 이상 3:4 이하, 전체 이미지 비율이 동일해야 함 | 800×400, 800×600 |

> 원문 확인 필요: 원문 HTML 의 권장 사이즈가 "800 400, 800 600" 형태로 곱셈 기호 없이 표기되어 있어 800×400, 800×600 으로 해석했다.

### 푸시

| 항목 | 값 |
|---|---|
| 지원 형식 | JPG, PNG |
| 파일 크기 | 최대 1MB |

## 결과 코드

원문은 결과 코드 표를 별도 페이지로 연결한다. 이 문서에는 조회 실패 예시의 `29009`(요청한 데이터 없음)만 나온다.
