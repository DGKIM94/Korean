# Hangul Tactile Designer — Portable v8

특정 Windows 사용자명이나 Python 설치 경로를 저장하지 않는 휴대용 패키지입니다. 다른 PC에서 복사한 오래된 `.venv`가 발견되면 자동으로 삭제하고 현재 PC의 Python으로 다시 생성합니다.

## 실행

1. ZIP을 완전히 압축 해제합니다.
2. `HangulTactileDesigner.exe`를 더블클릭합니다.
3. 첫 실행 때 필요한 Python 패키지를 현재 폴더의 `.venv`에 설치합니다.

EXE가 차단되면 `START_HERE_HangulTactileDesigner.cmd`를 실행하세요. 권장 환경은 Windows 10/11과 64-bit Python 3.11 또는 3.12입니다.

## v8 핵심 수정

### 1. 현재 Arduino 코드 그대로 사용

Arduino firmware를 새 버전으로 바꿀 필요가 없습니다. 사용자가 제공한 현재 코드를 그대로 포함했습니다.

- `korean2_no_relay_dual_device_18ch_softpwm.ino`
- `dual_device_temporal_controller.ino`

두 파일의 내용은 사용자가 제공한 코드와 같습니다.

### 2. `/i`, `/d` motion command 보존

다음 raw command는 고정 PWM 값으로 변환하지 않고 그대로 전송합니다.

```text
#5/150.#5/d,4/i/100.#4/150
```

따라서 더 이상 아래처럼 `128` 값으로 바뀌지 않습니다.

```text
#5=255/150.#4=128,5=128/100.#4=255/150
```

현재 Arduino 문법으로 표현할 수 없는 staggered overlap이 설정되면 ramp를 임의 변환하지 않고 오류 메시지를 표시합니다. 이 경우 SOA를 앞 자극 duration 이상으로 설정해야 합니다.

### 3. 자음 duration 기준 기본값 300 ms

일반 자음→모음 SOA는 앞 자음의 실제 컴파일 duration을 사용해 자동 분기합니다.

- duration ≤ 300 ms: 짧은 자음 SOA
- duration > 300 ms: 긴 자음 SOA

기준값은 고정이 아니며 고급 설정에서 변경할 수 있습니다.

### 4. motion도 실제 길이별 SOA 설정

기존의 하나짜리 `모션` 유형을 다음 두 유형으로 나눴습니다.

- 짧은 모션
- 긴 모션

모션의 실제 컴파일 duration과 `모션 duration 기준`을 비교해 고급 SOA 행렬의 행과 열을 자동 선택합니다. 기본 모션 기준도 300 ms이며 고급 설정에서 변경할 수 있습니다.

### 5. 고급 설정 위치

오른쪽 `음절 타이밍` 패널에서 아래 버튼을 누릅니다.

```text
고급 duration·유형·pair SOA
```

고급 창 상단에서 다음을 설정할 수 있습니다.

- 자음 duration 기준
- 모션 duration 기준

아래 SOA 행렬에는 `짧은 모션`과 `긴 모션`이 별도 행·열로 표시됩니다. 특정 자모 pair override가 있으면 행렬보다 우선합니다.

### 6. 음절·단어 경계는 ISI

- 음절 경계 ISI: 앞 음절의 모든 자극이 끝난 뒤부터 다음 음절 초성 시작까지
- 단어 경계 ISI: 앞 단어의 모든 자극이 끝난 뒤부터 다음 단어 첫 초성 시작까지

### 7. 화면 깨짐 수정 유지

낮은 화면 높이와 Windows 고배율 환경에서도 오른쪽 타이밍 패널이 내부 스크롤되며 라벨과 입력창 높이를 유지합니다.

## SOA 적용 우선순위

1. 특정 자모 pair override
2. 일반 자음→모음: 실제 자음 duration의 짧음/김 규칙
3. 모션이 포함된 경계: 실제 모션 duration의 짧은 모션/긴 모션 행렬
4. 나머지: 고급 유형 행렬 또는 기본 SOA

Composite 편집 화면에서 각 Step에 직접 입력한 SOA는 해당 Step의 개별값으로 사용됩니다.

## 주요 파일

- `HangulTactileDesigner.exe`: Windows 64-bit 부트스트랩 실행기
- `hangul_tactile_designer.py`: 전체 메인 소스
- `hangul_voice_backend.py`: 음성 인식·학습 백엔드
- `hangul_tactile_default_setup.json`: 기본 디자인과 timing 설정
- `korean2_no_relay_dual_device_18ch_softpwm.ino`: 현재 Arduino 코드 사본
- `reset_local_environment.bat`: 로컬 `.venv` 초기화
- `diagnose_environment.bat`: 실행 환경 진단
- `build_standalone_exe.bat`: PyInstaller 독립 실행 폴더 생성

## 문제 해결

1. 프로그램과 Python 창을 모두 닫습니다.
2. `reset_local_environment.bat`를 실행합니다.
3. `START_HERE_HangulTactileDesigner.cmd`를 다시 실행합니다.
4. 계속 실패하면 `diagnose_environment.bat`로 `environment_diagnostic.txt`를 생성합니다.
