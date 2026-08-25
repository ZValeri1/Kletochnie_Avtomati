"""
stage3.py
=========
Этап 3: Моделирование облучения металла гамма-излучением.

Наследует класс MetalLattice и добавляет:
1. Влияние интенсивности облучения на вероятности перемещения (p ~ 1/r^alpha_eff).
2. Генерацию новых вакансий (радиационные повреждения).
3. Визуализацию: сравнение структур, график зависимости длины прыжка от интенсивности, GIF.
"""

import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
from matplotlib.animation import FuncAnimation, PillowWriter
from pathlib import Path

from metal_lattice import MetalLattice

# ================================================================
# ПАРАМЕТРЫ МОДЕЛИ
# ================================================================
# Если файл состояния от этапа 2 не найден, будут использованы эти параметры
GRID_SIZE = 15
PARTICLE_RATIO = 0.85
MAX_RADIUS = 5
ALPHA = 3
SEED = 42

# Параметры облучения
IRRADIATION_INTENSITY = 0.5  # Интенсивность облучения (0.0 - нет, 1.0 - сильное)
K_COEFFICIENT = 2.0  # Коэффициент влияния облучения на alpha
VACANCY_CREATION_RATE = 0.02  # Вероятность создания новой вакансии за шаг (на 1 ячейку)

NUM_STEPS = 40  # Количество шагов анимации
OUTPUT_GIF = 'stage3_animation.gif'
INPUT_STATE = 'stage2_final_state_5x5.json'


# ================================================================
# КЛАСС ОБЛУЧАЕМОГО МЕТАЛЛА
# ================================================================
class IrradiatedMetalLattice(MetalLattice):
    """
    Расширяет базовый класс MetalLattice для моделирования облучения.
    """

    def __init__(self, irradiation_intensity=0.0, k_coefficient=2.0,
                 vacancy_creation_rate=0.0, **kwargs):
        super().__init__(**kwargs)
        self.irradiation_intensity = irradiation_intensity
        self.k_coefficient = k_coefficient
        self.vacancy_creation_rate = vacancy_creation_rate

        # Статистика длин прыжков для анализа
        self.jump_distances = []

    def compute_transition_probabilities(self, particle_pos, vacancies):
        """
        Модифицированный закон: p ~ 1/r^alpha_eff.
        Чем выше интенсивность облучения, тем меньше alpha_eff,
        тем выше вероятность дальних прыжков.
        """
        # Эффективный alpha уменьшается с ростом интенсивности
        # Если intensity = 0, alpha_eff = alpha (как в этапе 2)
        effective_alpha = self.alpha / (1.0 + self.k_coefficient * self.irradiation_intensity)

        distances = []
        valid_vacancies = []

        for v in vacancies:
            r = np.sqrt(np.sum((particle_pos - v) ** 2))
            # При облучении можно немного увеличить эффективный радиус поиска
            if 0 < r <= self.max_radius:
                distances.append(r)
                valid_vacancies.append(v)

        if len(distances) == 0:
            return []

        # Вероятность ~ 1/r^effective_alpha
        weights = np.array([1.0 / (r ** effective_alpha) for r in distances])
        probs = weights / weights.sum()

        return [(v, r, p) for v, r, p in zip(valid_vacancies, distances, probs)]

    def simulate_step(self):
        """
        Шаг симуляции с учетом облучения:
        1. Перемещение частицы (по модифицированному закону).
        2. Создание новых вакансий (радиационные повреждения).
        """
        # 1. Стандартное перемещение (использует переопределенный метод вероятностей)
        result = super().simulate_step()

        if result is not None:
            p_pos, v_pos, prob, r = result
            self.jump_distances.append(r)

        # 2. Радиационные повреждения: гамма-кванты выбивают атомы
        if self.vacancy_creation_rate > 0 and self.irradiation_intensity > 0:
            particles = self.get_particles()
            if len(particles) > 0:
                # Количество новых вакансий зависит от интенсивности и размера решетки
                num_new_vacancies = int(
                    self.vacancy_creation_rate * self.irradiation_intensity * (self.size ** 3)
                )
                # Ограничиваем, чтобы не выбить все частицы
                num_new_vacancies = min(num_new_vacancies, len(particles) - 1)

                if num_new_vacancies > 0:
                    # Случайно выбираем частицы и превращаем их в вакансии
                    indices = np.random.choice(len(particles), size=num_new_vacancies, replace=False)
                    for idx in indices:
                        self.lattice[tuple(particles[idx])] = 0

        # Сохраняем состояние в историю
        self.history.append(self.lattice.copy())
        return result


# ================================================================
# ВИЗУАЛИЗАЦИЯ 1: Сравнение структур "До" и "После"
# ================================================================
def compare_structures(lattice_before, lattice_after):
    """Сравнение 3D структур до и после облучения."""
    fig = plt.figure(figsize=(16, 8))
    fig.suptitle('Сравнение структуры металла: До и После облучения', fontsize=16, fontweight='bold')

    for idx, (lat, title) in enumerate([(lattice_before, 'До облучения'),
                                        (lattice_after, 'После облучения')], 1):
        ax = fig.add_subplot(1, 2, idx, projection='3d')
        particles = np.argwhere(lat.lattice == 1)
        vacancies = np.argwhere(lat.lattice == 0)

        if len(particles) > 0:
            ax.scatter(particles[:, 0], particles[:, 1], particles[:, 2],
                       c='blue', s=10, alpha=0.4, label='Частицы')
        if len(vacancies) > 0:
            ax.scatter(vacancies[:, 0], vacancies[:, 1], vacancies[:, 2],
                       c='red', s=30, alpha=0.8, label=f'Вакансии ({len(vacancies)})',
                       edgecolors='darkred', linewidths=0.5)

        ax.set_xlabel('X');
        ax.set_ylabel('Y');
        ax.set_zlabel('Z')
        ax.set_title(title)
        ax.legend(fontsize=8)
        ax.set_xlim(0, lat.size);
        ax.set_ylim(0, lat.size);
        ax.set_zlim(0, lat.size)

    plt.tight_layout()
    plt.show()


# ================================================================
# ВИЗУАЛИЗАЦИЯ 2: График зависимости длины прыжка от интенсивности
# ================================================================
def plot_jump_distance_vs_intensity(base_lattice_state):
    """
    Запускает короткие симуляции с разной интенсивностью облучения
    и строит график средней длины прыжка.
    """
    print("\n" + "=" * 60)
    print("Анализ влияния интенсивности облучения...")
    print("=" * 60)

    intensities = np.linspace(0.0, 2.0, 11)  # от 0 до 2.0
    mean_distances = []

    for I in intensities:
        # Создаем копию решетки для каждого теста
        lat = IrradiatedMetalLattice(
            irradiation_intensity=I,
            k_coefficient=K_COEFFICIENT,
            vacancy_creation_rate=0.0,  # Отключаем создание вакансий для чистоты эксперимента
            size=base_lattice_state.size,
            particle_ratio=0.85,  # Игнорируем, т.к. загружаем состояние
            max_radius=base_lattice_state.max_radius,
            alpha=base_lattice_state.alpha,
            seed=SEED
        )
        lat.lattice = base_lattice_state.lattice.copy()
        lat.reset_history()

        # Делаем 50 шагов
        lat.simulate_steps(50)

        if len(lat.jump_distances) > 0:
            mean_distances.append(np.mean(lat.jump_distances))
        else:
            mean_distances.append(0.0)

        print(f"  Интенсивность I={I:.2f} -> Средняя длина прыжка: {mean_distances[-1]:.3f}")

    # Построение графика
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(intensities, mean_distances, 'b-o', linewidth=2, markersize=8, label='Средняя длина прыжка')
    ax.set_xlabel('Интенсивность облучения (I)', fontsize=12)
    ax.set_ylabel('Среднее расстояние перемещения (r)', fontsize=12)
    ax.set_title('Влияние гамма-излучения на дальность перемещения частиц', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=11)

    plt.tight_layout()
    plt.show()


# ================================================================
# ВИЗУАЛИЗАЦИЯ 3: GIF-анимация процесса облучения
# ================================================================
def create_irradiation_animation(lattice, num_steps=40, filename='stage3_animation.gif'):
    """Создает GIF-анимацию процесса облучения."""
    print(f"\nСимуляция облучения ({num_steps} шагов)...")

    # Выполняем симуляцию
    for step in range(num_steps):
        lattice.simulate_step()
        if (step + 1) % 10 == 0:
            print(f"  Шаг {step + 1}: Вакансий стало {np.sum(lattice.lattice == 0)}")

    # Создаем анимацию
    fig = plt.figure(figsize=(10, 8))
    ax = fig.add_subplot(111, projection='3d')
    fig.suptitle('Процесс облучения металла', fontsize=14, fontweight='bold')

    def animate(frame):
        ax.clear()
        if frame >= len(lattice.history):
            return

        current_lattice = lattice.history[frame]
        particles = np.argwhere(current_lattice == 1)
        vacancies = np.argwhere(current_lattice == 0)

        if len(vacancies) > 0:
            ax.scatter(vacancies[:, 0], vacancies[:, 1], vacancies[:, 2],
                       c='red', s=25, alpha=0.8, label='Вакансии',
                       edgecolors='darkred', linewidths=0.5)
        if len(particles) > 0:
            ax.scatter(particles[:, 0], particles[:, 1], particles[:, 2],
                       c='blue', s=10, alpha=0.5, label='Частицы')

        ax.set_xlabel('X');
        ax.set_ylabel('Y');
        ax.set_zlabel('Z')
        ax.set_title(f'Шаг {frame}/{len(lattice.history) - 1}\n'
                     f'Вакансий: {len(vacancies)} (было {len(lattice.history[0][lattice.history[0] == 0])})')
        ax.set_xlim(0, lattice.size);
        ax.set_ylim(0, lattice.size);
        ax.set_zlim(0, lattice.size)

        if frame == 0:
            ax.legend(loc='upper left', fontsize=8)

    anim = FuncAnimation(fig, animate, frames=len(lattice.history), interval=300, repeat=True)

    print(f"Сохранение анимации в {filename}...")
    anim.save(filename, writer=PillowWriter(fps=3), dpi=80)
    plt.close()
    print(f"✓ Анимация сохранена: {filename}")

    # Показываем финальный кадр
    fig2 = plt.figure(figsize=(10, 8))
    ax2 = fig2.add_subplot(111, projection='3d')
    fig2.suptitle('Финальная структура после облучения', fontsize=14, fontweight='bold')

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

    ax2.set_xlabel('X');
    ax2.set_ylabel('Y');
    ax2.set_zlabel('Z')
    ax2.legend(fontsize=9)
    plt.tight_layout()
    plt.show()


# ================================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ================================================================
def main():
    print("=" * 60)
    print("ЭТАП 3: Моделирование облучения металла")
    print("=" * 60)

    # 1. Загрузка состояния из этапа 2 (или создание нового)
    if Path(INPUT_STATE).exists():
        print(f"\nЗагрузка состояния из {INPUT_STATE}...")
        lattice_before = MetalLattice.load_state(INPUT_STATE)
    else:
        print(f"\nФайл {INPUT_STATE} не найден. Создаем новую решетку...")
        lattice_before = MetalLattice(
            size=GRID_SIZE, particle_ratio=PARTICLE_RATIO,
            max_radius=MAX_RADIUS, alpha=ALPHA, seed=SEED
        )

    # Сохраняем копию "до облучения" для сравнения
    # (создаем новый объект, чтобы история не мешала)
    lattice_before_copy = MetalLattice(
        size=lattice_before.size, particle_ratio=lattice_before.particle_ratio,
        max_radius=lattice_before.max_radius, alpha=lattice_before.alpha, seed=SEED
    )
    lattice_before_copy.lattice = lattice_before.lattice.copy()

    # 2. Создание облучаемой решетки
    lattice_irradiated = IrradiatedMetalLattice(
        irradiation_intensity=IRRADIATION_INTENSITY,
        k_coefficient=K_COEFFICIENT,
        vacancy_creation_rate=VACANCY_CREATION_RATE,
        size=lattice_before.size,
        particle_ratio=lattice_before.particle_ratio,
        max_radius=lattice_before.max_radius,
        alpha=lattice_before.alpha,
        seed=SEED
    )
    # Копируем точное состояние из этапа 2
    lattice_irradiated.lattice = lattice_before.lattice.copy()
    lattice_irradiated.reset_history()

    print(f"\nПараметры облучения:")
    print(f"  Интенсивность (I): {IRRADIATION_INTENSITY}")
    print(f"  Коэффициент k: {K_COEFFICIENT}")
    print(f"  Скорость создания вакансий: {VACANCY_CREATION_RATE}")

    # 3. Визуализация 1: Сравнение До/После (сначала покажем "До", потом запустим облучение)
    print("\n--- Визуализация 1: Начальное состояние ---")
    # Запускаем симуляцию, чтобы получить состояние "После"
    lattice_irradiated.simulate_steps(NUM_STEPS)

    compare_structures(lattice_before_copy, lattice_irradiated)

    # 4. Визуализация 2: График зависимости
    plot_jump_distance_vs_intensity(lattice_before_copy)

    # 5. Визуализация 3: GIF анимация (запускаем заново с чистого состояния)
    print("\n--- Визуализация 3: Создание GIF анимации ---")
    lattice_for_gif = IrradiatedMetalLattice(
        irradiation_intensity=IRRADIATION_INTENSITY,
        k_coefficient=K_COEFFICIENT,
        vacancy_creation_rate=VACANCY_CREATION_RATE,
        size=lattice_before.size,
        particle_ratio=lattice_before.particle_ratio,
        max_radius=lattice_before.max_radius,
        alpha=lattice_before.alpha,
        seed=SEED
    )
    lattice_for_gif.lattice = lattice_before.lattice.copy()
    lattice_for_gif.reset_history()

    create_irradiation_animation(lattice_for_gif, num_steps=NUM_STEPS, filename=OUTPUT_GIF)

    print("\n" + "=" * 60)
    print("✓ Этап 3 завершен!")
    print("=" * 60)


if __name__ == '__main__':
    main()