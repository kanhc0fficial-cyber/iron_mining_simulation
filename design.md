# 东鞍山选矿全流程DCS仿真系统 — 软件工程实现设计

**版本**：v1.0  
**对应业务文档**：选矿仿真系统设计文档.md v1.0

---

## 1. 总体架构

### 1.1 设计目标

以 Python 单进程、纯数值计算的方式，在 60 s 步长下仿真 ≥ 30 天（43 200 步）的矿选全流程，输出约 200 个 DCS 时序变量与 2 个精矿品位目标变量，供 TFe 软测量模型训练使用。

### 1.2 整体分层

```
┌──────────────────────────────────────────────────────────────┐
│                        Simulator（顶层编排）                   │
│  step(t) : 按拓扑顺序调用各子系统 step，收集输出               │
└────────┬──────────┬─────────────┬──────────────┬─────────────┘
         │          │             │              │
    DisturbanceLayer  MagSepSystem  TowerMillSystem  FlotationSystem
    （第0层）        （磁选段）      （塔磨段）         （浮选段）
         │                                              │
    BallMillInput                              LabAssayer
    （球磨溢流边界）                            （化验时滞 + 品位输出）
```

所有子系统之间通过**纯 Python dict（信号总线 `bus`）** 传递中间物理量，不共享可变状态。

---

## 2. 项目目录结构

```
iron_mining_simulation/
├── sim/
│   ├── __init__.py
│   ├── simulator.py          # 顶层 Simulator 类
│   ├── config.py             # 全局常量 & 可调参数（唯一参数入口）
│   ├── rng.py                # 随机数管理（可复现种子）
│   ├── layers/
│   │   ├── disturbance.py    # 第0层：外生扰动 d(t)
│   │   ├── ball_mill.py      # 球磨溢流边界输入
│   │   ├── mag_sep.py        # 第3章：磁选段
│   │   ├── tower_mill.py     # 第4章：塔磨段
│   │   └── flotation.py      # 第5章：浮选段
│   ├── utils/
│   │   ├── pid.py            # 通用离散 PID 控制器
│   │   ├── thermal.py        # 通用热力学一阶 ODE 辅助
│   │   ├── sensor.py         # 传感器噪声 / 漂移 / 故障模型
│   │   └── buffer.py         # 时滞循环缓冲（用于流程时滞）
│   └── output/
│       ├── writer.py         # 增量写 Parquet / CSV
│       └── schema.py         # 输出列名与单位注册表
├── scripts/
│   ├── run_simulation.py     # CLI 入口
│   └── calibrate.py          # 标定点自测脚本（断言检验）
├── tests/
│   ├── test_disturbance.py
│   ├── test_mag_sep.py
│   ├── test_tower_mill.py
│   ├── test_flotation.py
│   └── test_integration.py
├── requirements.txt
└── README.md
```

---

## 3. 核心数据结构

### 3.1 信号总线 `bus: dict[str, float]`

每步 `step(t)` 开始时由上游子系统写入、下游子系统读取。键名即最终 CSV/Parquet 列名，与 DCS 变量命名保持一致（见 `schema.py`）。

**约定**：
- 物理隐藏状态以 `_x_` 前缀标识（不写入最终输出）：`_x_g_mag`、`_x_d80_ball` 等。
- DCS 可观测量直接用 DCS 标签名：`agg_mag_excit_voltage`、`MC1_FET503_AI` 等。
- 目标变量：`y_fx_xin1`、`y_fx_xin2`。

### 3.2 系统内部状态 `state: dict[str, float]`

每个子系统维护自己的 `state` dict（上一步的积分量），不暴露给其他子系统。子系统只通过 `bus` 交换信息。

### 3.3 时滞缓冲 `RingBuffer`

```python
class RingBuffer:
    def __init__(self, capacity: int, default: float): ...
    def push(self, value: float) -> None: ...
    def peek(self, delay_steps: int) -> float: ...  # 读取 delay_steps 步前的值
```

用于磁选→塔磨（15~30 min）、塔磨→浮选（30~60 min）、化验时滞（120~240 min）。

---

## 4. 各模块详细设计

### 4.1 `config.py` — 参数中心

```python
@dataclass(frozen=True)
class SimConfig:
    dt: int = 60                   # 步长（秒）
    n_steps: int = 43_200          # 总步数（30天）
    seed: int = 42

@dataclass
class DisturbanceConfig:
    d1_mean: float = 0.3149        # 球磨溢流TFe品位均值
    d1_phi: float = 0.99
    d1_sigma: float = 0.0005
    # d2/d3/d4 同构 …
    cov_d1d2: float = -0.6         # d1-d2 地质相关性

@dataclass
class MagSepConfig:
    k_wm_Fe: float = ...           # 弱磁富集系数（标定值）
    k_wm_Si: float = ...
    beta_wm0: float = 0.4523       # 文档标定：弱磁回收率
    lambda_strong: float = ...     # 强磁逻辑斜率（标定值）
    R0_coil: float = ...           # 线圈冷阻
    alpha_Cu: float = 0.00393
    tau_thermal: float = 1800.0    # 热时间常数（s）
    Vnom: float = 380.0
    Tblowdown: float = 28800.0     # 排污周期（s）
    # … 完整参数列表见 config.py

@dataclass
class TowerMillConfig:
    k_mill: float = ...
    P0: float = ...
    P_rated: float = 1120.0        # kW
    alpha0_cyc: float = ...
    tau_bearing: float = 900.0
    tau_stator: float = 900.0
    tau_reducer: float = 2700.0
    p_fault_bearing: float = 0.002
    # …

@dataclass
class FlotationConfig:
    kSi0: float = ...              # 浮选速率常数基值
    alpha_kSi: float = ...
    beta_kSi: float = ...
    Qtd_star: float = ...          # 非单调拐点（g/t）
    tau_lab_min: int = 120         # 化验最短时滞（min）
    tau_lab_max: int = 240
    sigma_lab: float = 0.12        # 化验误差（%TFe）
    delta_12: float = 0.2          # 两线系统偏置
    p_fault_froth: float = 0.005
    # …
```

所有 `Config` 对象在 `run_simulation.py` 中构造，以构造函数参数传入各子系统，**不使用全局变量**。

---

### 4.2 `rng.py` — 随机数管理

```python
class RNGFactory:
    """
    为每个子系统分配独立的 np.random.Generator，保证
    各子系统随机流独立且整体可复现。
    """
    def __init__(self, master_seed: int):
        self._rng = np.random.default_rng(master_seed)

    def get(self, name: str) -> np.random.Generator:
        """同名称每次返回相同派生种子的 Generator"""
        seed = int(self._rng.integers(2**31))
        return np.random.default_rng(seed)
```

---

### 4.3 `layers/disturbance.py` — 第0层

**类**：`DisturbanceLayer`

**状态**：`state = {xi_d1, xi_d2, xi_d3, xi_d4}`（OU过程残差）

**核心方法**：

```python
def step(self, t: int) -> dict:
    """
    返回：
        _x_d1, _x_d2, _x_d3, _x_d4   (隐藏扰动，不写入最终输出)
    更新：
        xi_d_i ← phi_i * xi_d_i + eta_i  (相关噪声，Cholesky分解)
        约束：clip 到物理可行范围
    """
```

**实现要点**：
- d1/d2 相关噪声用 Cholesky 分解（`np.linalg.cholesky`）从独立标准正态生成。
- 每步结果写入 bus 的 `_x_d*` 键，不输出到 CSV。

---

### 4.4 `layers/ball_mill.py` — 球磨溢流边界

**类**：`BallMillInput`

**状态**：`state = {m_ball, rho_ball, d80_ball}`（3个 AR(1) 过程）

**核心方法**：

```python
def step(self, bus: dict) -> None:
    """
    从 bus 读取：_x_d3（可磨性）
    写入 bus：
        _x_m_ball, _x_rho_ball, _x_d80_ball
        _x_f_minus25  (由 d80 的反S形函数计算)
    """
```

**实现要点**：
- `f_{-25μm}` 用 `scipy.special.expit` 实现反S形（避免溢出）。
- 三条球磨线视为并联且相关（相关系数 ρ ≈ 0.7），用同一扰动分量驱动。

---

### 4.5 `layers/mag_sep.py` — 磁选段

**类**：`MagSepSystem`

**内部子对象**：

| 子对象 | 职责 |
|--------|------|
| `WeakMagSep` | 弱磁选（准静态代数） |
| `PreConcentrator` | 强磁前浓缩（一阶滞后） |
| `StrongMagSep` | 强磁 + 扫强磁（磁力-曳力 Sigmoid） |
| `MagLevelPID` | 选矿液位 PID（使用 `pid.PIDController`） |
| `CoilThermal` | 线圈热力学（使用 `thermal.FirstOrderThermal`） |

**状态变量**（全量）：

```
xi_V_exc, T_coil, L_mag, b_L_mag,          # 励磁/液位/漂移
blowdown_counter, xi_f_ring, xi_f_pul,     # 操作员设定量
delta_Vgrid                                 # 电网波动
```

**核心物理计算顺序**：

```
1. 励磁：V_exc → I_exc（热阻） → T_coil（焦耳热ODE）
2. 弱磁：d1,m_ball → g_wmag, beta_wm, m_wm_tail
3. 前浓缩：m_wm_tail → m_conc_out（一阶滞后）
4. 强磁：B(I_exc), f_ring → beta_strong → g_strong, g_sweep
5. 混磁精矿：加权平均 → g_mag, m_mag
6. 液位：质量守恒ODE → L_mag → PID → u_v1, u_v2
7. 排污阀：周期脉冲逻辑
8. 电机：β_strong, m_in → I_motor
9. 所有量加噪声/漂移后写入 bus
```

**标定断言**（在 `calibrate.py` 中验证，不在运行时执行）：

| 条件 | 期望结果 | 容差 |
|------|---------|------|
| d1=31.49%, I_exc=额定 | g_wmag ≈ 51.29% | ±0.5% |
| 弱磁稳态 | beta_wm ≈ 45.23% | ±1% |
| d1=23.91%, 强磁稳态 | g_strong ≈ 40.73%, beta_strong ≈ 67.99% | ±1% |

---

### 4.6 `layers/tower_mill.py` — 塔磨段

**类**：`TowerMillSystem`

**内部子对象**：

| 子对象 | 职责 |
|--------|------|
| `PumpPoolDyn` | 泵池液位质量守恒 ODE |
| `CycloneClassifier` | 旋流器分级（分流比方程） |
| `TowerMillGrinding` | 研磨动力学（Bond 功指数） |
| `BearingThermal` × 2 | 滑动轴承热力学（带老化 + 故障注入） |
| `StatorThermal` × 2 | 定子热力学 |
| `ReducerThermal` | 减速机油温热力学 |
| `PumpPID` | 泵频 PID |

**时滞处理**：

```python
# 磁选→塔磨 段间时滞（15~30 min = 15~30步）
self._magsep_to_tm_buf = RingBuffer(capacity=60, default=0.0)   # 存 m_mag, g_mag
# 塔磨内部闭路返回时滞（塔磨研磨时间 5~15 min = 5~15步）
self._discharge_buf    = RingBuffer(capacity=30, default=0.0)   # 存 Q_pump_out
# 每步：先 push 当前值，再从 delay_steps 处 peek 读取延迟值
```

**注意**：`TowerMillSystem.step()` 中，应先读取 `_magsep_to_tm_buf.peek(τ_magtm_steps)` 获得延迟后的磁选输出，再更新内部状态，最后 `push` 当前磁选输出，保证时序正确。

**关键物理量传递链**：

```
m_mag(bus, 经 magsep_to_tm_buf 延迟) → PumpPoolDyn → Q_pump_out
           → CycloneClassifier → Q_ov, Q_sand, alpha_ov
           → TowerMillGrinding → d80_disch, f_325_ov, P_mech
           → 各热力学模型 → T_b1, T_b2, T_sA, T_sB, T_red, T_red_out
           → 泵电流方程 → I_cyc_pump, I_ov_pump
TowerMill 同时向 bus 写入 _x_Q_ov（供 FlotationSystem 经时滞缓冲后读取）
```

**故障注入**（`sensor.py` 提供）：

```python
def inject_fault(val: float, p_fault: float, fault_val: float, rng) -> float:
    return fault_val if rng.random() < p_fault else val
```

`T_b1_DCS = inject_fault(T_b1, p_fault=0.002, fault_val=-287.04, rng=self._rng)`

**标定断言**：

| 条件 | 期望结果 | 容差 |
|------|---------|------|
| 稳态给矿 | P_mech ∈ [730, 950] kW | — |
| 稳态 | f_{-325μm,ov} ≥ 92.5% | — |
| 旋流器分级效率 | ≈ 24.81% | ±2% |

---

### 4.7 `layers/flotation.py` — 浮选段

**类**：`FlotationSystem`

**内部子对象**：

| 子对象 | 职责 |
|--------|------|
| `PreConcentratorNT` | 浮选前浓缩（一阶 ODE） |
| `FloatCell` × N | 单浮选槽（液位 + 泡沫层 + 浓度 ODE） |
| `DrugPump` × M | 加药泵（螺杆泵频率 → 流量 → 电流） |
| `pHDyn` × 2 | 每系列 pH 动力学 |
| `AgitatorTank` × K | 搅拌槽（温度 ODE + 蒸汽阀 PID） |
| `BlowerPair` | 两台并联鼓风机压力曲线 |
| `SumpPumpPID` × L | 各泵池液位 PID + 渣浆泵 |
| `LabAssayer` | 化验时滞 + 品位生成 |

**两系列对称处理**：

Series I（`X1`）和 Series II（`X2`）使用相同的 `FloatCell` 类，以不同参数实例化（允许 5~10% 差异）。

**塔磨→浮选段间时滞**：

```python
# FlotationSystem.__init__ 中
self._tm_to_flo_buf = RingBuffer(capacity=120, default=0.0)  # 最长60 min = 60步，容量120留余量
# step() 中：先 peek(τ_tm2flo_steps) 读取延迟后的塔磨溢流，再 push 当前值
```

**浮选拓扑（数组化）**：

```python
# 流向说明：
#   pulp  = 底流 / 矿浆主流
#   froth = 泡沫产品流
# 输出端：
#   JX froth  → 最终精矿（写入 bus _x_conc_out，传给 LabAssayer）
#   SX3 froth → 最终尾矿（丢弃，不写输出）
# 两个泵池（LT_1601/1602/1603）隐含在逆流返回箭头中：
#   SX1 bottom + JX tailings → pool → CX1 feed
#   CX froth   + SX2 bottom  → pool → SX1 feed
#   SX3 bottom               → pool → SX2 feed

TOPOLOGY = [
    # 粗选主流
    ("feed",  "CX1", "pulp"), ("CX1", "CX2", "pulp"), ("CX2", "CX3", "pulp"),
    # 粗选→精选
    ("CX3", "JX", "pulp"),
    # 精选：精矿泡沫输出，尾矿逆流返回粗选给矿
    ("JX", "conc_out", "froth"),   # 最终精矿
    ("JX", "CX1",      "pulp"),    # 精选尾矿返回粗选（via LT_1601）
    # 粗选泡沫→扫选（via LT_1602）
    ("CX1", "SX1", "froth"), ("CX2", "SX1", "froth"), ("CX3", "SX1", "froth"),
    # 扫选内部主流（泡沫向下游传递）
    ("SX1", "SX2", "froth"), ("SX2", "SX3", "froth"),
    # 扫选尾矿输出
    ("SX3", "tails_out", "froth"),
    # 扫选底流逆流返回（SX1→CX via LT_1601；SX2→SX1 via LT_1602；SX3→SX2 via LT_1603）
    ("SX1", "CX1", "pulp"),
    ("SX2", "SX1", "pulp"),
    ("SX3", "SX2", "pulp"),
]
```

每步按拓扑顺序迭代更新各槽状态（Gauss-Seidel 顺序，单次迭代足够，因 Δt=60s 远小于槽时间常数）。

**浮选速率常数非单调实现**：

```python
def k_Si(Q_td, pH, Q_air, C_Ca, config):
    # 非单调部分用两段分段函数避免除零
    efficacy = (Q_td ** config.alpha) / (1 + np.exp(config.beta * (Q_td - config.Qtd_star)))
    pH_effect = pH ** config.gamma / (1 + config.k_Ca * C_Ca)
    air_factor = Q_air / config.Q_air_nom
    return config.kSi0 * efficacy * pH_effect * air_factor
```

**`LabAssayer` — 化验时滞**：

```python
class LabAssayer:
    def __init__(self, config, rng):
        # 用 RingBuffer 实现可变时滞（每次化验取随机 τ_lab）
        self._buf = RingBuffer(capacity=300, default=0.66)  # 240 min / 60s = 240步

    def step(self, C_Fe_JX: float, C_Si_JX: float, t: int) -> tuple[float | None, float | None]:
        """
        返回 (TFe_xin1, TFe_xin2)；若本步不是化验报出时刻则返回 (None, None)
        化验频率：每班 1~2 次（4~8h），用 Poisson 采样决定本步是否报出
        """
```

**标定断言**：

| 条件 | 期望结果 | 容差 |
|------|---------|------|
| Q_TD=2100 g/t 稳态 | 精矿 TFe ≈ 67.43%, 尾矿 ≈ 12.86% | ±0.5% |
| Q_TD=1500 g/t 稳态 | 精矿 TFe ≈ 66.56%, 尾矿 ≈ 20.90% | ±0.5% |
| 稳态 pH | 9.2 ~ 10.1 | — |

---

### 4.8 `utils/pid.py` — 离散 PID

```python
class PIDController:
    def __init__(self, Kp, Ki, Kd, dt, u_min=0.0, u_max=1.0, anti_windup=True): ...
    def step(self, setpoint: float, measurement: float) -> float:
        """返回控制输出 u，内部维护积分项与上次误差"""
```

**反积分饱和**（`anti_windup=True`）：当输出饱和时停止积分项累加，防止液位阀震荡过大。

---

### 4.9 `utils/thermal.py` — 热力学一阶 ODE

```python
class FirstOrderThermal:
    """
    tau * dT/dt = Q_heat - k_cool*(T - T_amb)
    离散化：前向欧拉，Δt=60s
    """
    def __init__(self, tau: float, k_cool: float, T_init: float): ...
    def step(self, Q_heat: float, T_amb: float, dt: float, noise: float = 0.0) -> float: ...
```

---

### 4.10 `utils/sensor.py` — 传感器模型

```python
def add_drift(val: float, b: float, sigma_b: float, rng) -> tuple[float, float]:
    """随机游走漂移：b_new = b + N(0, sigma_b²)；返回 (val + b_new, b_new)"""

def add_noise(val: float, sigma: float, rng) -> float:
    """加性高斯白噪声"""

def inject_fault(val: float, p_fault: float, fault_val: float, rng) -> float:
    """以概率 p_fault 替换为异常值 fault_val"""
```

---

### 4.11 `simulator.py` — 顶层编排

```python
class Simulator:
    def __init__(self, sim_cfg, dist_cfg, mag_cfg, tm_cfg, flo_cfg):
        self._disturbance = DisturbanceLayer(dist_cfg, rng_factory.get("dist"))
        self._ball_mill   = BallMillInput(sim_cfg, rng_factory.get("ball"))
        self._mag_sep     = MagSepSystem(mag_cfg, rng_factory.get("mag"))
        self._tower_mill  = TowerMillSystem(tm_cfg, rng_factory.get("tm"))
        self._flotation   = FlotationSystem(flo_cfg, rng_factory.get("flo"))
        self._writer      = Writer(output_path)
        self._bus: dict   = {}

    def run(self) -> None:
        for t in range(self._cfg.n_steps):
            self._bus.clear()
            self._bus["t"] = t

            self._disturbance.step(self._bus)   # 写 _x_d1~4
            self._ball_mill.step(self._bus)      # 写 _x_m_ball, _x_d80_ball …
            self._mag_sep.step(self._bus)        # 写磁选DCS变量 + _x_g_mag, _x_m_mag
            self._tower_mill.step(self._bus)     # 写塔磨DCS变量 + _x_f325_ov
            self._flotation.step(self._bus)      # 写浮选DCS变量 + y_fx_xin1/2

            self._writer.write_row(self._bus)    # 仅写非 _x_ 前缀的键

    def warm_up(self, n_steps: int = 300) -> None:
        """预热 n_steps 步使动态状态到达稳态（不写输出）"""
```

**步骤顺序保证**：蒸馏时滞由 `RingBuffer` 内部处理，不影响调用顺序；各子系统 `step` 只读不属于自己子系统的 bus 键，不存在写写冲突。

---

### 4.12 `output/writer.py` — 输出

- 默认格式：**Parquet**（`pyarrow`），每 1 000 行批写一次，降低内存开销。
- 备选：CSV（`--format csv` 命令行选项）。
- 输出列由 `schema.py` 中的 `OUTPUT_COLUMNS` 列表决定（自动过滤 `_x_` 前缀列）。
- 最终精矿品位 `y_fx_xin1/2` 列在无化验报出时刻填 `NaN`，下游训练时按需插值或删除。

---

## 5. 开环激励模式

为使仿真TFe方差达到目标（≥4.0），支持开环（持续激励）模式：

```python
@dataclass
class ExcitationConfig:
    mode: str = "closed_loop"   # "closed_loop" | "open_loop_PRBS"
    prbs_amplitude: float = 0.3 # 加药量扰动幅度（相对均值）
    d1_sigma_scale: float = 1.0 # d1 扰动幅度倍率（开环建议 3~5）
    pH_control: bool = True     # False 则 pH 自由漂移
```

开环模式下，加药量 PID 替换为 PRBS 信号（`scipy.signal.max_len_seq` 生成）。

---

## 6. 测试策略

| 测试类型 | 文件 | 验收标准 |
|---------|------|--------|
| 单元：标定点断言 | `calibrate.py` | 弱磁/强磁/塔磨/浮选稳态值在容差内 |
| 单元：随机数可复现 | `test_disturbance.py` | 相同 seed 产生相同输出序列 |
| 单元：PID 收敛 | `test_mag_sep.py` | 液位阶跃响应在 300s 内稳定 |
| 单元：热力学稳态 | `test_tower_mill.py` | T_coil/T_bearing 稳态值在设计范围内 |
| 集成：30天仿真 | `test_integration.py` | TFe均值66~68%，方差≥4.0（开环），无 NaN/Inf |
| 集成：列完整性 | `test_integration.py` | 输出 DataFrame 列数 ≥ 200，无缺失列 |

---

## 7. 依赖

```
numpy>=1.26
scipy>=1.12
pandas>=2.0
pyarrow>=14.0
```

无仿真框架依赖（不使用 SimPy、OpenModelica 等），保证运行速度和可移植性。全程无 GPU 需求，30天仿真目标运行时间 < 5 分钟（单核）。

---

## 8. 关键设计决策与权衡

| 决策 | 选择 | 原因 |
|------|------|------|
| 时间积分方法 | 前向欧拉（Δt=60s） | 所有物理时间常数 >> 60s，欧拉误差可忽略；无需 RK4 增加复杂度 |
| 浮选拓扑迭代 | Gauss-Seidel 单次迭代 | 槽时间常数（分钟级）远大于 Δt，单次已足够收敛 |
| 参数管理 | `dataclass`（不可变） | 防止运行时意外修改参数；支持 `asdict()` 序列化 |
| 随机数隔离 | 每子系统独立 `Generator` | 修改一个子系统不影响其他子系统的随机序列 |
| 时滞实现 | `RingBuffer`（定长循环队列） | 避免 `deque` 的 Python 对象开销；容量固定防内存增长 |
| 输出格式 | Parquet（主）/ CSV（备） | Parquet 压缩率高（~5×）；CSV 便于快速查看 |
| 化验时刻 | Poisson 采样（非固定间隔） | 复现真实化验的随机性；避免固定周期带来的频率混叠 |

---

## 9. 变量命名规范

| 前缀/后缀 | 含义 |
|----------|------|
| `_x_` 前缀 | 隐藏物理状态，不写入输出 |
| `_DCS` 后缀（内部变量名） | 含噪声/漂移的可观测量 |
| 小写 + 下划线 | Python 变量/方法名 |
| 大写缩写 + 数字 | 与 DCS 标签保持一致（如 `MC1_TM204_AI`） |
| `agg_` 前缀 | 聚合/设备级 DCS 标签（与原始标签保持一致） |

---

*本文档描述软件工程实现层面的设计，数学公式含义请参考《选矿仿真系统设计文档.md》。*
