# Hangul Tactile Designer — Portable v17

Windows 사용자명이나 Python 설치 경로를 저장하지 않는 휴대용 버전입니다. 다른 PC에서 복사된 오래된 `.venv`는 현재 PC 기준으로 다시 생성할 수 있습니다.

## 실행

1. ZIP을 완전히 압축 해제합니다.
2. `HangulTactileDesigner.exe`를 실행합니다.
3. 처음 실행할 때 Python 환경이 없으면 자동 설치를 진행합니다.

실행 문제가 있으면 `REINSTALL_FOR_THIS_PC.cmd`를 실행하세요.

## v17 핵심 변경: 전체 타이밍을 ISI로 통일

Composite, CV, CVC, 복합 종성, 음절 경계, 단어 경계의 모든 값이 **end-to-start ISI**로 동작합니다.

ISI는 다음 의미입니다.

```text
앞 자극이 완전히 끝남
→ 설정한 ISI만큼 기다림
→ 다음 자극 시작
```

예를 들어 앞 모음 자극의 실제 길이가 1000 ms이고 모음→종성 ISI가 500 ms라면 종성은 모음 시작 후 1500 ms에 시작합니다. 따라서 자극 길이가 길어져도 겹침 오류나 별도의 예외 보정이 필요하지 않습니다.

### 기본값

- Composite 내부 ISI: 150 ms
- CV 자음→모음 ISI: 250 ms
- CVC 첫 자음→모음 ISI: 250 ms
- CVC 모음→종성 ISI: 250 ms
- 복합 종성 내부 ISI: 150 ms
- 음절 경계 ISI: 350 ms
- 단어 경계 ISI: 650 ms

### Duration 분기

자음과 모션의 duration 기준은 유지됩니다. 다만 duration은 **어떤 ISI 행을 사용할지 선택하는 용도**일 뿐이며, 행렬의 숫자는 항상 앞 자극 종료 후 기다리는 시간입니다.

### 고급 ISI 설정

고급 설정에서는 다음을 조절할 수 있습니다.

- 자음 duration 분기 기준
- 모션 duration 분기 기준
- 자극 유형별 ISI 행렬
- 특정 자모 pair ISI override

CV와 CVC 첫 자음 구간의 `짧음`·`김` 행은 오른쪽 기본 설정과 동기화됩니다.

## 기존 SOA 셋업 자동 변환

`hangul_tactile_setups/default.json`이 v16 이하 형식이면 실행할 때 자동으로 ISI 형식으로 변환해 불러옵니다.

- Composite와 일반 구간은 이전 물리적 간격에 가까운 단순 ISI 값으로 변환
- 기존 pair override도 가능한 범위에서 ISI로 변환
- 기존 Composite Step SOA는 실제 앞 Step duration을 반영해 ISI로 변환
- 변환 후 `저장`을 누르면 v17 형식으로 저장

원본 JSON 파일은 자동으로 덮어쓰지 않으며, 사용자가 저장할 때만 변경됩니다.

## 자동 default 불러오기

프로그램 시작 시 다음 파일을 자동으로 불러옵니다.

```text
hangul_tactile_setups/default.json
```

대소문자가 다른 `Default.json`도 인식합니다. 파일이 없으면 내장 기본 셋업으로 새 `default.json`을 생성합니다.

## 유지된 기능

- 현재 Arduino firmware 그대로 사용
- raw `/i`, `/d` 명령 보존
- 디자인 편집 및 자모 미리보기
- 선택 자모 객관식 학습
- Top200 XLSX 기반 일반 CV/CVC 퀴즈
- 보이스 퀴즈
- 결과 CSV 저장
- 고해상도/고배율 UI 잘림 수정
- 다른 PC에서 Python 자동 설치

## 일반 퀴즈

일반 퀴즈는 `syllable_top200.xlsx`에서 읽은 실제 한글 음절만 사용합니다.

- 셀에 단어가 있으면 음절 단위로 분리
- 중복 음절 제거
- 선택한 CV/CVC, 기본·쌍자음, 기본·복합 모음 조건으로 필터링
- 현재 디자인과 ISI 규칙으로 컴파일 가능한 음절만 출제

## 주요 파일

- `HangulTactileDesigner.exe`: Windows 실행기
- `hangul_tactile_designer.py`: 메인 프로그램
- `hangul_voice_backend.py`: 음성 퀴즈 백엔드
- `hangul_tactile_default_setup.json`: v17 기본 디자인
- `korean2_no_relay_dual_device_18ch_softpwm.ino`: 현재 Arduino 코드 사본
- `REINSTALL_FOR_THIS_PC.cmd`: 현재 PC용 Python 환경 재설치
- `diagnose_environment.bat`: 실행 환경 진단
