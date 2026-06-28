# BatSim — Battery & BMS Circuit Simulator

PSpice/Simulink 스타일의 GUI 회로 편집기 + Python 기반 배터리/BMS 시뮬레이션 엔진.
Pure Python (PyQt6 + NumPy/SciPy) 으로 구현.

---

## 1. Vision & Scope

- **목표**: 사용자가 드래그앤드롭으로 전기/전자 회로(R, L, C, V, I, Switch, Diode, MOSFET 등)를 구성하고,
  여기에 **배터리 셀/팩**과 **BMS 블록**을 결합하여 과도/정상 상태 시뮬레이션을 수행.
- **차별점**: PSpice/Simulink는 배터리 모델링이 빈약. BatSim은 **기본 등가회로(Rint, Thevenin, 2RC, n-RC)**
  부터 **고급 전기화학 모델(SPM, SPMe, P2D/Doyle-Fuller-Newman)** 까지 모델 스왑이 가능.
- **사용성**: 노드 스냅, 와이어 자동 라우팅, 파라미터 인스펙터, 라이브 파형 뷰어.

## 2. Architecture (모듈 구성)

```
batsim_core/
├── batsim_core/
│   ├── __init__.py
│   ├── app.py                  # 진입점 (QApplication)
│   ├── ui/                     # PyQt6 GUI
│   │   ├── main_window.py      # 메인 윈도우 (메뉴/툴바/도크)
│   │   ├── canvas/             # QGraphicsView 기반 스키매틱 편집기
│   │   │   ├── scene.py        # 그리드, 스냅, 선택
│   │   │   ├── component_item.py  # 부품 그래픽 아이템 (드래그 가능)
│   │   │   ├── wire_item.py    # 와이어 (직교 라우팅)
│   │   │   └── port_item.py    # 핀/포트 (스냅 연결)
│   │   ├── palette.py          # 좌측 부품 라이브러리 패널 (드래그 소스)
│   │   ├── inspector.py        # 우측 파라미터 편집 패널
│   │   ├── waveform_view.py    # 결과 파형 (pyqtgraph)
│   │   └── simulation_dialog.py# 트랜지언트/DC/AC 설정 다이얼로그
│   ├── components/             # 부품 정의(심볼 + 모델 메타)
│   │   ├── base.py             # Component 베이스
│   │   ├── passive.py          # R, L, C
│   │   ├── sources.py          # V, I, Pulse, Sine
│   │   ├── semiconductor.py    # Diode, BJT, MOSFET
│   │   ├── switches.py         # Switch, Relay
│   │   └── battery.py          # Battery 셀/팩 (모델 선택 가능)
│   ├── bms/                    # BMS 블록
│   │   ├── soc_estimator.py    # CC, EKF, UKF
│   │   ├── balancer.py         # Passive/Active balancing
│   │   ├── protection.py       # OV/UV/OC/OT
│   │   └── controller.py       # 충방전 제어
│   ├── models/                 # 배터리 수학 모델
│   │   ├── base.py             # BatteryModel ABC
│   │   ├── rint.py             # Rint (내부저항만)
│   │   ├── thevenin.py         # 1-RC
│   │   ├── n_rc.py             # n-RC (2RC, 3RC)
│   │   ├── spm.py              # Single Particle Model
│   │   ├── spme.py             # SPM + electrolyte
│   │   └── p2d.py              # Doyle-Fuller-Newman (PyBaMM 연동 옵션)
│   ├── engine/                 # 시뮬레이션 엔진
│   │   ├── netlist.py          # 회로 → 네트리스트 변환
│   │   ├── mna.py              # Modified Nodal Analysis (DC/AC/Transient)
│   │   ├── solver.py           # 적분기 (Backward Euler, Trapezoidal, BDF)
│   │   ├── nonlinear.py        # Newton-Raphson
│   │   └── stamps.py           # 부품별 MNA 스탬프 (배터리 포함)
│   ├── io/
│   │   ├── project.py          # .batsim (JSON/YAML) 저장/로드
│   │   └── export.py           # CSV/PNG/SPICE netlist 내보내기
│   └── utils/
│       └── logging.py
├── assets/
│   ├── icons/                  # 부품 SVG 심볼
│   └── examples/               # 샘플 회로 (.batsim)
├── tests/
│   ├── test_mna.py
│   ├── test_battery_models.py
│   └── test_bms.py
├── requirements.txt
├── pyproject.toml
└── README.md
```

### 핵심 설계 원칙
1. **UI ↔ Engine 분리**: UI는 회로 그래프(JSON-serializable)만 생성, Engine은 그래프를 입력으로 받음.
2. **플러그형 배터리 모델**: `BatteryModel` ABC를 구현하면 어떤 모델이든 회로에 끼워 넣을 수 있음.
3. **MNA 통합**: 배터리도 MNA 스탬프(전압원 + 동적 상태)로 표현 → 일반 회로 부품과 동시 풀이.
4. **확장성**: 부품/모델 추가 시 클래스 한 개만 등록.

## 3. UI/UX 핵심 요구사항

- 좌측 **부품 팔레트** → 캔버스로 **드래그앤드롭**.
- 부품 클릭 시 우측 **인스펙터** 에서 파라미터(저항값, 배터리 모델 종류/용량 등) 편집.
- 핀에서 마우스 드래그 → **자동 직교 와이어 라우팅** + 스냅.
- **그리드 스냅**, 회전(R), 미러, 멀티 셀렉트, 복사/붙여넣기, undo/redo (QUndoStack).
- **시뮬레이션 결과 파형**은 별도 도크에 pyqtgraph로 표시. 노드/부품 우클릭 → "Probe".
- 프로젝트 저장 포맷: 사람이 읽을 수 있는 JSON.

## 4. 기술 스택

- **Python 3.11+**
- **PyQt6** (UI), **pyqtgraph** (파형)
- **NumPy / SciPy** (선형대수, ODE)
- **PyBaMM** (선택) — P2D 등 고급 모델
- **pytest** (테스트)
- 패키징: `pyproject.toml` + (추후) PyInstaller로 단일 실행 파일

## 5. 구현 단계 (Phase)

### Phase 0 — 프로젝트 부트스트랩
- 폴더 구조, `pyproject.toml`, `requirements.txt`, 기본 `app.py` 빈 윈도우.

### Phase 1 — 회로 편집기 UI 골격
- QGraphicsScene + 그리드/스냅, 부품 팔레트(R/V/GND), 드래그앤드롭, 와이어 연결, 인스펙터, 저장/로드.

### Phase 2 — MNA 엔진 (선형 DC/Transient)
- R, L, C, V, I 스탬프 → DC operating point → Backward Euler 트랜지언트.
- pyqtgraph 파형 뷰어 연동.

### Phase 3 — 비선형 + 반도체
- Newton-Raphson, Diode, MOSFET(Level-1), Switch.

### Phase 4 — 배터리 모델 (기본 등가회로)
- `BatteryModel` ABC, **Rint → Thevenin(1RC) → n-RC** 구현.
- OCV-SOC 룩업, 쿨롱 카운팅으로 SOC 갱신.
- MNA 스탬프(가변 전압원 + RC 동특성).

### Phase 5 — BMS 블록
- SOC Estimator (CC, EKF), Protection (OV/UV/OC/OT), Passive Balancer, 충방전 컨트롤러.
- 팩(직병렬) 구성 지원.

### Phase 6 — 고급 배터리 모델
- SPM, SPMe 자체 구현. P2D는 PyBaMM 어댑터.
- 인스펙터에서 모델 종류를 드롭다운으로 스왑 가능.

### Phase 7 — 마감
- 예제 회로(셀 1개 충방전, 4S BMS 보호, DC-DC + 배터리 등), 문서, 패키징, 설치 마법사.

## 6. 위험 요소 / 결정 필요 항목

- **MNA 자체 구현 vs Ngspice 바인딩**: 자체 구현은 배터리 통합이 자유롭지만 비용이 큼. → **자체 구현으로 시작**, 필요 시 ngspice-shared로 교체.
- **P2D 자체 구현은 매우 무거움** → PyBaMM 의존을 옵션으로.
- **실시간 파형 갱신 성능**: 큰 시뮬레이션은 백그라운드 QThread + 청크 업데이트 필요.

## 7. Definition of Done (MVP — Phase 4 완료 시점)

- 사용자가 GUI에서 V-source + R + Battery(Thevenin) + Load 회로를 드래그로 구성.
- "Run Transient" 클릭 → 1초간 시뮬, 배터리 단자전압/SOC/전류 파형 확인.
- 프로젝트를 .batsim 으로 저장/로드 가능.


