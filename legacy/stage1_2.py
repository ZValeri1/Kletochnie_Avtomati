"""
stage1_2.py
===========
Этапы 1 и 2: Базовая структура металла и механизм перемещения частиц.

Использует класс MetalLattice из модуля metal_lattice.

Этап 1: Визуализация начальной структуры (3D + 2D срезы)
Этап 2: Механизм перемещения частиц (стрелки вероятностей, график p(r), GIF)

В конце сохраняет состояние решётки в файл stage2_final_state.json
для использования в этапе 3.
"""

import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
from matplotlib.animation import FuncAnimation, PillowWriter
from pathlib import Path

from metal_lattice import MetalLattice

# ================================================================
# ПАРАМЕТРЫ МОДЕЛИ (можно менять)
# ================================================================
# ================================================================
# ПАРАМЕТРЫ МОДЕЛИ (Настройка для наглядности 5x5x5)
# ================================================================
GRID_SIZE = 5               # Маленькая решетка для наглядности (всего 125 ячеек)
PARTICLE_RATIO = 0.85       # 85% частиц (~106), 15% вакансий (~19)
MAX_RADIUS = 2              # Радиус поиска (аналог окрестности s из статьи)
ALPHA = 2                   # p ~ 1/r^2 (умеренное предпочтение ближних вакансий)
NUM_STEPS = 15              # Меньше шагов, т.к. вакансий всего ~19
NUM_PARTICLES_SHOW = 3      # Показывать стрелки только для 3 частиц
SEED = 42                   # Фиксируем случайность для стабильности
OUTPUT_GIF = 'stage2_animation_5x5.gif'
OUTPUT_STATE = 'stage2_final_state_5x5.json'

# ================================================================
# ЭТАП 1: Базовая структура металла
# ================================================================
def stage1_visualization(lattice: MetalLattice):
    """
    Визуализация начальной структуры металла.

    Показывает:
    - 3D scatter plot частиц и вакансий
    - Три 2D среза (XY, XZ, YZ) по центру решётки
    """
    particles = lattice.get_particles()
    vacancies = lattice.get_vacancies()

    print("=" * 60)
    print("ЭТАП 1: Базовая структура металла")
    print("=" * 60)
    lattice.print_statistics()

    # Создаём фигуру 2x2
    fig = plt.figure(figsize=(16, 12))
    fig.suptitle('ЭТАП 1: Начальная структура металла', fontsize=16, fontweight='bold')

    # --- 3D визуализация ---
    ax1 = fig.add_subplot(221, projection='3d')

    # Частицы (синие, полупрозрачные, маленькие)
    if len(particles) > 0:
        ax1.scatter(particles[:, 0], particles[:, 1], particles[:, 2],
                    c='blue', s=10, alpha=0.3, label=f'Частицы ({len(particles)})')

    # Вакансии (красные, более заметные)
    if len(vacancies) > 0:
        ax1.scatter(vacancies[:, 0], vacancies[:, 1], vacancies[:, 2],
                    c='red', s=30, alpha=0.7, label=f'Вакансии ({len(vacancies)})',
                    edgecolors='darkred', linewidths=0.5)

    ax1.set_xlabel('X')
    ax1.set_ylabel('Y')
    ax1.set_zlabel('Z')
    ax1.set_title('3D структура металла')
    ax1.legend(loc='upper left', fontsize=8)

    # --- 2D срезы ---
    mid = lattice.size // 2
    cmap = plt.cm.RdYlBu

    # Срез XY (по Z)
    ax2 = fig.add_subplot(222)
    slice_xy = lattice.lattice[:, :, mid]
    im2 = ax2.imshow(slice_xy, cmap=cmap, origin='lower', vmin=0, vmax=1)
    ax2.set_title(f'Срез XY (Z={mid})')
    ax2.set_xlabel('X')
    ax2.set_ylabel('Y')
    fig.colorbar(im2, ax=ax2, label='1=частица (синий), 0=вакансия (красный)')

    # Срез XZ (по Y)
    ax3 = fig.add_subplot(223)
    slice_xz = lattice.lattice[:, mid, :]
    im3 = ax3.imshow(slice_xz, cmap=cmap, origin='lower', vmin=0, vmax=1)
    ax3.set_title(f'Срез XZ (Y={mid})')
    ax3.set_xlabel('X')
    ax3.set_ylabel('Z')
    fig.colorbar(im3, ax=ax3, label='1=частица, 0=вакансия')

    # Срез YZ (по X)
    ax4 = fig.add_subplot(224)
    slice_yz = lattice.lattice[mid, :, :]
    im4 = ax4.imshow(slice_yz, cmap=cmap, origin='lower', vmin=0, vmax=1)
    ax4.set_title(f'Срез YZ (X={mid})')
    ax4.set_xlabel('Y')
    ax4.set_ylabel('Z')
    fig.colorbar(im4, ax=ax4, label='1=частица, 0=вакансия')

    plt.tight_layout()
    plt.show()  # Блокирует до закрытия окна


# ================================================================
# ЭТАП 2: Механизм перемещения частиц
# ================================================================
def stage2_visualization(lattice: MetalLattice):
    """
    Визуализация механизма перемещения частиц.

    Показывает:
    - 3D scatter plot со стрелками вероятностей
    - График зависимости p(r)
    """
    particles = lattice.get_particles()
    vacancies = lattice.get_vacancies()

    print("\n" + "=" * 60)
    print("ЭТАП 2: Механизм перемещения частиц")
    print("=" * 60)

    # Тест вычисления вероятностей для одной частицы
    if len(particles) > 0 and len(vacancies) > 0:
        p0 = particles[0]
        probs = lattice.compute_transition_probabilities(p0, vacancies)
        print(f"\nПример для частицы {p0}:")
        print(f"  Найдено вакансий в радиусе {lattice.max_radius}: {len(probs)}")
        if len(probs) > 0:
            sorted_probs = sorted(probs, key=lambda x: -x[2])
            print("  Топ-3 наиболее вероятных перемещения:")
            for v, r, p in sorted_probs[:3]:
                print(f"    -> вакансия {v}, r={r:.2f}, p={p:.4f}")
            print(f"  Сумма вероятностей: {sum(x[2] for x in probs):.4f}")

    # Создаём фигуру 1x2
    fig = plt.figure(figsize=(18, 8))
    fig.suptitle('ЭТАП 2: Механизм перемещения частиц', fontsize=16, fontweight='bold')

    # --- 3D визуализация со стрелками ---
    ax1 = fig.add_subplot(121, projection='3d')

    # Частицы (серые, маленькие)
    if len(particles) > 0:
        ax1.scatter(particles[:, 0], particles[:, 1], particles[:, 2],
                    c='lightblue', s=5, alpha=0.3, label='Все частицы')

    # Вакансии (красные)
    if len(vacancies) > 0:
        ax1.scatter(vacancies[:, 0], vacancies[:, 1], vacancies[:, 2],
                    c='red', s=30, alpha=0.6, label='Вакансии', marker='o',
                    edgecolors='darkred', linewidths=0.5)

    # Выбираем несколько частиц для показа стрелок
    if len(particles) > 0:
        num_show = min(NUM_PARTICLES_SHOW, len(particles))
        indices = np.random.choice(len(particles), size=num_show, replace=False)

        for idx in indices:
            p = particles[idx]
            probs_list = lattice.compute_transition_probabilities(p, vacancies)

            for v, r, prob in probs_list:
                # Рисуем стрелку от частицы к вакансии
                # Прозрачность и толщина пропорциональны вероятности
                # Усиливаем для наглядности (prob*5), но ограничиваем 1.0
                alpha = min(prob * 5, 1.0)
                linewidth = prob * 15  # толщина стрелки

                ax1.quiver(p[0], p[1], p[2],
                           v[0] - p[0], v[1] - p[1], v[2] - p[2],
                           color='green', alpha=alpha,
                           arrow_length_ratio=0.15,
                           linewidth=linewidth)

        # Подсвечиваем выбранные частицы
        selected = particles[indices]
        ax1.scatter(selected[:, 0], selected[:, 1], selected[:, 2],
                    c='blue', s=100, alpha=0.9,
                    label=f'Выбранные частицы ({num_show})',
                    edgecolors='black', linewidths=1.5, zorder=10)

    ax1.set_xlabel('X')
    ax1.set_ylabel('Y')
    ax1.set_zlabel('Z')
    ax1.set_title(f'Стрелки вероятностей (p ~ 1/r^{lattice.alpha})\n'
                  f'Толщина/прозрачность ~ вероятность')
    ax1.legend(loc='upper left', fontsize=8)

    # --- График вероятности от расстояния ---
    ax2 = fig.add_subplot(122)

    # Теоретическая кривая p ~ 1/r^alpha
    r_theory = np.linspace(0.5, lattice.max_radius, 100)
    p_theory = 1.0 / (r_theory ** lattice.alpha)
    ax2.plot(r_theory, p_theory, 'b-', linewidth=2.5,
             label=f'Теория: p ~ 1/r^{lattice.alpha}', zorder=5)

    # Реальные данные для нескольких частиц (разные цвета)
    if len(particles) > 0 and len(vacancies) > 0:
        colors = ['red', 'orange', 'purple', 'brown']
        num_test = min(3, len(particles))

        for i in range(num_test):
            p = particles[i * len(particles) // num_test]
            probs_list = lattice.compute_transition_probabilities(p, vacancies)
            if probs_list:
                rs = [x[1] for x in probs_list]
                ps = [x[2] for x in probs_list]
                ax2.scatter(rs, ps, c=colors[i], s=60, zorder=10,
                            label=f'Частица {p}', alpha=0.7)
                # Соединяем точки линией
                sorted_data = sorted(zip(rs, ps))
                rs_sorted = [x[0] for x in sorted_data]
                ps_sorted = [x[1] for x in sorted_data]
                ax2.plot(rs_sorted, ps_sorted, '--', color=colors[i], alpha=0.5)

    ax2.set_xlabel('Расстояние r', fontsize=12)
    ax2.set_ylabel('Вероятность p', fontsize=12)
    ax2.set_title('Зависимость вероятности перемещения от расстояния')
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.3)
    ax2.set_xlim(0, lattice.max_radius + 0.5)

    plt.tight_layout()
    plt.show()  # Блокирует до закрытия окна


# ================================================================
# ЭТАП 2b: GIF-анимация перемещения частиц
# ================================================================
def stage2_animation(lattice: MetalLattice, num_steps: int = 30,
                     filename: str = 'stage2_animation.gif'):
    """
    Создаёт GIF-анимацию пошагового перемещения частиц.

    Аргументы:
        lattice: объект MetalLattice
        num_steps: количество шагов симуляции
        filename: имя выходного GIF-файла
    """
    print(f"\nСимуляция {num_steps} шагов...")

    # Выполняем симуляцию
    moves_info = []
    for step in range(num_steps):
        result = lattice.simulate_step()
        if result is not None:
            p_pos, v_pos, prob, r = result
            moves_info.append((p_pos.copy(), v_pos.copy(), prob, r))
            print(f"  Шаг {step + 1:2d}: частица {p_pos} -> вакансия {v_pos}, "
                  f"p={prob:.4f}, r={r:.2f}")
        else:
            print(f"  Шаг {step + 1:2d}: нет доступных перемещений")
            moves_info.append(None)

    print(f"\nВсего шагов в истории: {len(lattice.history)}")
    print(f"Совершено перемещений: {len(moves_info)}")

    # Создаём анимацию
    fig = plt.figure(figsize=(10, 8))
    ax = fig.add_subplot(111, projection='3d')
    fig.suptitle('Анимация перемещения частиц', fontsize=14, fontweight='bold')

    def animate(frame):
        ax.clear()

        if frame >= len(lattice.history):
            return

        current_lattice = lattice.history[frame]
        particles = np.argwhere(current_lattice == 1)
        vacancies = np.argwhere(current_lattice == 0)

        # Вакансии (красные)
        if len(vacancies) > 0:
            ax.scatter(vacancies[:, 0], vacancies[:, 1], vacancies[:, 2],
                       c='red', s=25, alpha=0.6, label='Вакансии',
                       edgecolors='darkred', linewidths=0.5)

        # Частицы (синие)
        if len(particles) > 0:
            ax.scatter(particles[:, 0], particles[:, 1], particles[:, 2],
                       c='blue', s=15, alpha=0.6, label='Частицы')

        # Показываем последнее перемещение стрелкой
        if frame > 0 and moves_info[frame - 1] is not None:
            p_pos, v_pos, prob, r = moves_info[frame - 1]
            ax.quiver(p_pos[0], p_pos[1], p_pos[2],
                      v_pos[0] - p_pos[0], v_pos[1] - p_pos[1], v_pos[2] - p_pos[2],
                      color='lime', alpha=0.9, arrow_length_ratio=0.2,
                      linewidth=3, zorder=10)
            # Подпись с вероятностью
            ax.text(v_pos[0] + 0.3, v_pos[1] + 0.3, v_pos[2] + 0.3,
                    f'p={prob:.3f}\nr={r:.2f}',
                    color='green', fontsize=9, fontweight='bold',
                    bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.7))

        ax.set_xlabel('X')
        ax.set_ylabel('Y')
        ax.set_zlabel('Z')
        ax.set_title(f'Шаг {frame}/{len(lattice.history) - 1}\n'
                     f'Частиц: {len(particles)}, Вакансий: {len(vacancies)}')
        ax.set_xlim(0, lattice.size)
        ax.set_ylim(0, lattice.size)
        ax.set_zlim(0, lattice.size)

        # Легенда только на первом кадре
        if frame == 0:
            ax.legend(loc='upper left', fontsize=8)

    anim = FuncAnimation(fig, animate, frames=len(lattice.history),
                         interval=500, repeat=True)

    # Сохраняем GIF
    print(f"\nСохранение анимации в {filename}...")
    anim.save(filename, writer=PillowWriter(fps=2), dpi=80)
    plt.close()
    print(f"✓ Анимация сохранена: {filename}")

    # Показываем финальное состояние
    fig2 = plt.figure(figsize=(10, 8))
    ax2 = fig2.add_subplot(111, projection='3d')
    fig2.suptitle('Финальное состояние после облучения', fontsize=14, fontweight='bold')

    final_lattice = lattice.history[-1]
    particles = np.argwhere(final_lattice == 1)
    vacancies = np.argwhere(final_lattice == 0)

    if len(vacancies) > 0:
        ax2.scatter(vacancies[:, 0], vacancies[:, 1], vacancies[:, 2],
                    c='red', s=25, alpha=0.7, label=f'Вакансии ({len(vacancies)})',
                    edgecolors='darkred', linewidths=0.5)
    if len(particles) > 0:
        ax2.scatter(particles[:, 0], particles[:, 1], particles[:, 2],
                    c='blue', s=15, alpha=0.6, label=f'Частицы ({len(particles)})')

    ax2.set_xlabel('X')
    ax2.set_ylabel('Y')
    ax2.set_zlabel('Z')
    ax2.set_title(f'Состояние после {num_steps} шагов перемещения')
    ax2.legend(loc='upper left', fontsize=9)

    plt.tight_layout()
    plt.show()  # Блокирует до закрытия окна


# ================================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ================================================================
def main():
    """Главная функция: запускает все этапы последовательно."""
    print("=" * 60)
    print("МОДЕЛИРОВАНИЕ ПЕРЕМЕЩЕНИЯ ЧАСТИЦ В МЕТАЛЛЕ")
    print("Этапы 1-2: Базовая структура и механизм перемещения")
    print("=" * 60)
    print(f"\nПараметры модели:")
    print(f"  Размер решётки: {GRID_SIZE}x{GRID_SIZE}x{GRID_SIZE}")
    print(f"  Доля частиц: {PARTICLE_RATIO * 100:.1f}%")
    print(f"  Макс. радиус поиска: {MAX_RADIUS}")
    print(f"  Параметр alpha: {ALPHA}")
    print(f"  Количество шагов: {NUM_STEPS}")
    print(f"  Seed: {SEED}")

    # Создаём решётку
    lattice = MetalLattice(
        size=GRID_SIZE,
        particle_ratio=PARTICLE_RATIO,
        max_radius=MAX_RADIUS,
        alpha=ALPHA,
        seed=SEED
    )

    # ЭТАП 1: Базовая структура
    stage1_visualization(lattice)

    # ЭТАП 2: Механизм перемещения (стрелки и график)
    stage2_visualization(lattice)

    # ЭТАП 2b: GIF-анимация
    stage2_animation(lattice, num_steps=NUM_STEPS, filename=OUTPUT_GIF)

    # Сохраняем состояние для этапа 3
    print("\n" + "=" * 60)
    print("Сохранение состояния для этапа 3...")
    print("=" * 60)
    lattice.save_state(OUTPUT_STATE)

    print("\n" + "=" * 60)
    print("✓ Все этапы 1-2 завершены!")
    print("=" * 60)
    print(f"\nСозданные файлы:")
    print(f"  - {OUTPUT_GIF} (анимация перемещения)")
    print(f"  - {OUTPUT_STATE} (состояние решётки для этапа 3)")
    print(f"\nТеперь можно запустить stage3.py для моделирования облучения.")


if __name__ == '__main__':
    main()