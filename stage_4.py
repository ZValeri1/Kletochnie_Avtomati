"""
stage4.py
=========
Этап 4: Циклический процесс облучения и восстановления структуры металла.
"""

import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
from matplotlib.animation import FuncAnimation, PillowWriter
from pathlib import Path

from metal_lattice import MetalLattice
from stage3 import IrradiatedMetalLattice


# ================================================================
# ПАРАМЕТРЫ МОДЕЛИ
# ================================================================
GRID_SIZE = 15
PARTICLE_RATIO = 0.85
MAX_RADIUS = 5
ALPHA = 3
SEED = 42

IRRADIATION_INTENSITY = 0.5
K_COEFFICIENT = 2.0
VACANCY_CREATION_RATE = 0.02

IRRADIATION_PHASE_DURATION = 20
RECOVERY_PHASE_DURATION = 30
NUM_CYCLES = 3
RECOVERY_PROBABILITY = 0.3

OUTPUT_GIF = 'stage4_animation.gif'
OUTPUT_PLOT = 'stage4_vacancy_cycles.png'
INPUT_STATE = 'stage2_final_state.json'


# ================================================================
# КЛАСС ЦИКЛИЧЕСКОГО ПРОЦЕССА
# ================================================================
class CyclicMetalLattice(IrradiatedMetalLattice):
    def __init__(self, recovery_probability=0.3, **kwargs):
        super().__init__(**kwargs)
        self.recovery_probability = recovery_probability
        self.phase_history = ['initial']  # Исправлено: начальное состояние

    def reset_history(self):
        """Переопределяем, чтобы очищать и phase_history тоже."""
        super().reset_history()
        self.phase_history = ['initial']

    def recovery_step(self):
        """
        Шаг фазы восстановления:
        1. Вакансии с вероятностью recovery_probability "залечиваются"
        2. Частицы диффундируют в ближайшие вакансии
        """
        vacancies = self.get_vacancies()
        particles = self.get_particles()

        # 1. Залечивание вакансий
        if len(vacancies) > 0:
            num_to_heal = int(len(vacancies) * self.recovery_probability)
            num_to_heal = min(num_to_heal, len(vacancies))
            if num_to_heal > 0:
                heal_indices = np.random.choice(len(vacancies), size=num_to_heal, replace=False)
                for idx in heal_indices:
                    self.lattice[tuple(vacancies[idx])] = 1

        # 2. Диффузия частиц (перемещение в вакансию)
        # Реализуем вручную, чтобы контролировать history
        vacancies = self.get_vacancies()  # обновляем после залечивания
        particles = self.get_particles()

        if len(particles) > 0 and len(vacancies) > 0:
            p_idx = np.random.randint(len(particles))
            p_pos = particles[p_idx]
            probs_list = self.compute_transition_probabilities(p_pos, vacancies)
            if len(probs_list) > 0:
                probs = np.array([x[2] for x in probs_list])
                v_idx = np.random.choice(len(probs_list), p=probs)
                v_pos, r, prob = probs_list[v_idx]
                self.lattice[tuple(p_pos)] = 0
                self.lattice[tuple(v_pos)] = 1

        # Добавляем состояние в историю ОДИН раз
        self.history.append(self.lattice.copy())
        self.phase_history.append('recovery')

        return None

    def simulate_cycle(self, irradiation_steps, recovery_steps):
        print(f"\n  Фаза облучения ({irradiation_steps} шагов):")
        for step in range(irradiation_steps):
            self.simulate_step()  # IrradiatedMetalLattice.simulate_step сам добавляет в history
            self.phase_history.append('irradiation')

        print(f"  Фаза восстановления ({recovery_steps} шагов):")
        for step in range(recovery_steps):
            self.recovery_step()  # recovery_step сам добавляет в history

        return len(self.history)


# ================================================================
# ВИЗУАЛИЗАЦИЯ 1: График цикличности
# ================================================================
def plot_vacancy_cycles(lattice, filename='stage4_vacancy_cycles.png'):
    print("\n" + "=" * 60)
    print("Визуализация 1: График цикличности процесса")
    print("=" * 60)

    vacancy_counts = []
    for state in lattice.history:
        num_vacancies = np.sum(state == 0)
        vacancy_counts.append(num_vacancies)

    steps = np.arange(len(vacancy_counts))
    phases = lattice.phase_history

    # Проверка согласованности длин
    if len(phases) != len(steps):
        print(f"️  Внимание: len(history)={len(steps)}, len(phase_history)={len(phases)}")
        # Выравниваем (берем минимум)
        min_len = min(len(phases), len(steps))
        steps = steps[:min_len]
        vacancy_counts = vacancy_counts[:min_len]
        phases = phases[:min_len]

    fig, ax = plt.subplots(figsize=(14, 7))

    # Цветной фон для фаз
    for i in range(len(steps) - 1):
        if phases[i] == 'irradiation':
            ax.axvspan(steps[i], steps[i+1], alpha=0.2, color='red')
        else:
            ax.axvspan(steps[i], steps[i+1], alpha=0.2, color='green')

    ax.plot(steps, vacancy_counts, 'b-', linewidth=2, label='Количество вакансий')
    ax.scatter(steps, vacancy_counts, c='blue', s=20, zorder=5)

    # Аннотации циклов
    cycle_length = IRRADIATION_PHASE_DURATION + RECOVERY_PHASE_DURATION
    for i in range(NUM_CYCLES):
        cycle_start = i * cycle_length
        cycle_mid = cycle_start + IRRADIATION_PHASE_DURATION // 2
        if cycle_mid < len(steps):
            ax.text(cycle_mid, max(vacancy_counts) * 1.05, f'Цикл {i+1}',
                    ha='center', fontsize=10, fontweight='bold', color='darkred')

    ax.set_xlabel('Шаг симуляции', fontsize=12)
    ax.set_ylabel('Количество вакансий', fontsize=12)
    ax.set_title('Циклический процесс облучения и восстановления металла',
                 fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)

    # Легенда фаз (объединенная)
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D
    legend_elements = [
        Patch(facecolor='red', alpha=0.3, label='Фаза облучения'),
        Patch(facecolor='green', alpha=0.3, label='Фаза восстановления'),
        Line2D([0], [0], color='blue', linewidth=2, label='Количество вакансий')
    ]
    ax.legend(handles=legend_elements, loc='upper right', fontsize=10)

    plt.tight_layout()
    plt.savefig(filename, dpi=150, bbox_inches='tight')
    print(f"✓ График сохранен: {filename}")
    plt.show()


# ================================================================
# ВИЗУАЛИЗАЦИЯ 2: Сравнение структур в ключевые моменты
# ================================================================
def compare_key_structures(lattice):
    print("\n" + "=" * 60)
    print("Визуализация 2: Сравнение структур в ключевые моменты")
    print("=" * 60)

    cycle_length = IRRADIATION_PHASE_DURATION + RECOVERY_PHASE_DURATION

    key_moments = [
        (0, 'Начало'),
        (min(IRRADIATION_PHASE_DURATION, len(lattice.history)-1), 'После 1-го облучения'),
        (min(cycle_length, len(lattice.history)-1), 'После 1-го восстановления'),
        (len(lattice.history) - 1, 'Конец симуляции')
    ]

    fig = plt.figure(figsize=(20, 5))

    for idx, (step_idx, title) in enumerate(key_moments, 1):
        if step_idx >= len(lattice.history):
            continue

        ax = fig.add_subplot(1, 4, idx, projection='3d')
        state = lattice.history[step_idx]
        particles = np.argwhere(state == 1)
        vacancies = np.argwhere(state == 0)

        if len(particles) > 0:
            ax.scatter(particles[:, 0], particles[:, 1], particles[:, 2],
                      c='blue', s=10, alpha=0.4, label=f'Частицы ({len(particles)})')
        if len(vacancies) > 0:
            ax.scatter(vacancies[:, 0], vacancies[:, 1], vacancies[:, 2],
                      c='red', s=30, alpha=0.8, label=f'Вакансии ({len(vacancies)})',
                      edgecolors='darkred', linewidths=0.5)

        ax.set_xlabel('X'); ax.set_ylabel('Y'); ax.set_zlabel('Z')
        ax.set_title(f'{title}\n(шаг {step_idx})', fontsize=10)
        ax.legend(fontsize=7, loc='upper left')
        ax.set_xlim(0, lattice.size); ax.set_ylim(0, lattice.size); ax.set_zlim(0, lattice.size)

    plt.suptitle('Эволюция структуры металла', fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.show()


# ================================================================
# ВИЗУАЛИЗАЦИЯ 3: GIF-анимация полного цикла
# ================================================================
def create_cyclic_animation(lattice, filename='stage4_animation.gif'):
    print(f"\n" + "=" * 60)
    print("Визуализация 3: GIF-анимация циклического процесса")
    print("=" * 60)

    fig = plt.figure(figsize=(10, 8))
    ax = fig.add_subplot(111, projection='3d')
    fig.suptitle('Циклический процесс облучения и восстановления',
                 fontsize=14, fontweight='bold')

    def animate(frame):
        ax.clear()
        if frame >= len(lattice.history):
            return

        state = lattice.history[frame]
        particles = np.argwhere(state == 1)
        vacancies = np.argwhere(state == 0)

        phase = lattice.phase_history[frame] if frame < len(lattice.phase_history) else 'unknown'
        phase_color = 'red' if phase == 'irradiation' else 'green'
        phase_name = 'ОБЛУЧЕНИЕ' if phase == 'irradiation' else 'ВОССТАНОВЛЕНИЕ'

        if len(vacancies) > 0:
            ax.scatter(vacancies[:, 0], vacancies[:, 1], vacancies[:, 2],
                      c='red', s=25, alpha=0.8, label=f'Вакансии ({len(vacancies)})',
                      edgecolors='darkred', linewidths=0.5)
        if len(particles) > 0:
            ax.scatter(particles[:, 0], particles[:, 1], particles[:, 2],
                      c='blue', s=10, alpha=0.5, label=f'Частицы ({len(particles)})')

        ax.set_xlabel('X'); ax.set_ylabel('Y'); ax.set_zlabel('Z')
        ax.set_title(f'Шаг {frame}/{len(lattice.history)-1}\n'
                    f'Фаза: {phase_name}\n'
                    f'Вакансий: {len(vacancies)}',
                    fontsize=11, color=phase_color, fontweight='bold')
        ax.set_xlim(0, lattice.size); ax.set_ylim(0, lattice.size); ax.set_zlim(0, lattice.size)

        if frame == 0:
            ax.legend(loc='upper left', fontsize=8)

    anim = FuncAnimation(fig, animate, frames=len(lattice.history), interval=400, repeat=True)

    print(f"Сохранение анимации в {filename}...")
    anim.save(filename, writer=PillowWriter(fps=2.5), dpi=80)
    plt.close()
    print(f"✓ Анимация сохранена: {filename}")

    # Показываем финальный кадр
    fig2 = plt.figure(figsize=(10, 8))
    ax2 = fig2.add_subplot(111, projection='3d')
    fig2.suptitle('Финальная структура после циклического процесса',
                  fontsize=14, fontweight='bold')

    final = lattice.history[-1]
    particles = np.argwhere(final == 1)
    vacancies = np.argwhere(final == 0)

    if len(vacancies) > 0:
        ax2.scatter(vacancies[:, 0], vacancies[:, 1], vacancies[:, 2],
                   c='red', s=25, alpha=0.8, label=f'Вакансии ({len(vacancies)})',
                   edgecolors='darkred', linewidths=0.5)
    if len(particles) > 0:
        ax2.scatter(particles[:, 0], particles[:, 1], particles[:, 2],
                   c='blue', s=10, alpha=0.5, label=f'Частицы ({len(particles)})')

    ax2.set_xlabel('X'); ax2.set_ylabel('Y'); ax2.set_zlabel('Z')
    ax2.legend(fontsize=9)
    plt.tight_layout()
    plt.show()


# ================================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ================================================================
def main():
    print("=" * 60)
    print("ЭТАП 4: Циклический процесс облучения и восстановления")
    print("=" * 60)

    if Path(INPUT_STATE).exists():
        print(f"\nЗагрузка состояния из {INPUT_STATE}...")
        initial_lattice = MetalLattice.load_state(INPUT_STATE)
    else:
        print(f"\nФайл {INPUT_STATE} не найден. Создаем новую решетку...")
        initial_lattice = MetalLattice(
            size=GRID_SIZE, particle_ratio=PARTICLE_RATIO,
            max_radius=MAX_RADIUS, alpha=ALPHA, seed=SEED
        )

    print(f"\nПараметры циклического процесса:")
    print(f"  Длительность фазы облучения: {IRRADIATION_PHASE_DURATION} шагов")
    print(f"  Длительность фазы восстановления: {RECOVERY_PHASE_DURATION} шагов")
    print(f"  Количество циклов: {NUM_CYCLES}")
    print(f"  Вероятность залечивания вакансий: {RECOVERY_PROBABILITY}")

    cyclic_lattice = CyclicMetalLattice(
        recovery_probability=RECOVERY_PROBABILITY,
        irradiation_intensity=IRRADIATION_INTENSITY,
        k_coefficient=K_COEFFICIENT,
        vacancy_creation_rate=VACANCY_CREATION_RATE,
        size=initial_lattice.size,
        particle_ratio=initial_lattice.particle_ratio,
        max_radius=initial_lattice.max_radius,
        alpha=initial_lattice.alpha,
        seed=SEED
    )
    cyclic_lattice.lattice = initial_lattice.lattice.copy()
    cyclic_lattice.reset_history()  # Теперь корректно сбрасывает и phase_history

    print("\n" + "=" * 60)
    print("Симуляция циклического процесса...")
    print("=" * 60)

    for cycle in range(NUM_CYCLES):
        print(f"\nЦикл {cycle + 1}/{NUM_CYCLES}:")
        cyclic_lattice.simulate_cycle(IRRADIATION_PHASE_DURATION, RECOVERY_PHASE_DURATION)
        final_vacancies = np.sum(cyclic_lattice.lattice == 0)
        print(f"  Вакансий в конце цикла: {final_vacancies}")

    plot_vacancy_cycles(cyclic_lattice, filename=OUTPUT_PLOT)
    compare_key_structures(cyclic_lattice)
    create_cyclic_animation(cyclic_lattice, filename=OUTPUT_GIF)

    print("\n" + "=" * 60)
    print("✓ Этап 4 завершен!")
    print("=" * 60)


if __name__ == '__main__':
    main()