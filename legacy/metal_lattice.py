"""
metal_lattice.py
================
Базовый класс для моделирования кристаллической решётки металла.
Используется в этапах 1, 2 и 3 проекта.

Класс реализует:
- Создание 3D решётки с частицами и вакансиями
- Вычисление вероятностей перемещения частиц (закон p ~ 1/r^alpha)
- Симуляцию пошагового перемещения частиц
- Сохранение/загрузку состояния решётки
- Статистический анализ структуры
"""

import numpy as np
import json
from pathlib import Path


class MetalLattice:
    """
    Класс, моделирующий кристаллическую решётку металла.

    Состояния ячеек:
        1 — частица (атом металла)
        0 — вакансия (свободное место)

    Параметры:
        size: размер решётки (size x size x size)
        particle_ratio: доля частиц (0..1)
        max_radius: максимальный радиус поиска вакансий
        alpha: степень зависимости вероятности от расстояния (p ~ 1/r^alpha)
        seed: случайное зерно для воспроизводимости (None = случайное)
    """

    def __init__(self, size=15, particle_ratio=0.85, max_radius=5,
                 alpha=2, seed=None):
        self.size = size
        self.particle_ratio = particle_ratio
        self.max_radius = max_radius
        self.alpha = alpha

        # Инициализация генератора случайных чисел
        if seed is not None:
            np.random.seed(seed)

        # Создание решётки: 1 = частица, 0 = вакансия
        self.lattice = np.random.choice(
            [0, 1],
            size=(size, size, size),
            p=[1 - particle_ratio, particle_ratio]
        )

        # История состояний (для анимации)
        self.history = [self.lattice.copy()]

        # Статистика перемещений
        self.moves_history = []  # список (p_pos, v_pos, prob, r)

    # ================================================================
    # ПОЛУЧЕНИЕ КООРДИНАТ
    # ================================================================

    def get_particles(self):
        """Возвращает массив координат всех частиц (shape: N x 3)."""
        return np.argwhere(self.lattice == 1)

    def get_vacancies(self):
        """Возвращает массив координат всех вакансий (shape: M x 3)."""
        return np.argwhere(self.lattice == 0)

    def get_state(self):
        """Возвращает копию текущей решётки."""
        return self.lattice.copy()

    # ================================================================
    # СТАТИСТИКА
    # ================================================================

    def get_statistics(self):
        """
        Возвращает словарь со статистикой текущей решётки.
        """
        particles = self.get_particles()
        vacancies = self.get_vacancies()
        total = self.size ** 3

        return {
            'size': self.size,
            'total_cells': total,
            'num_particles': len(particles),
            'num_vacancies': len(vacancies),
            'particle_ratio': len(particles) / total,
            'vacancy_ratio': len(vacancies) / total,
            'alpha': self.alpha,
            'max_radius': self.max_radius,
            'num_steps_simulated': len(self.history) - 1,
            'num_moves_made': len(self.moves_history)
        }

    def print_statistics(self):
        """Выводит статистику в консоль."""
        stats = self.get_statistics()
        print(f"Размер решётки: {stats['size']}x{stats['size']}x{stats['size']}")
        print(f"Всего ячеек: {stats['total_cells']}")
        print(f"Частиц: {stats['num_particles']} ({stats['particle_ratio'] * 100:.1f}%)")
        print(f"Вакансий: {stats['num_vacancies']} ({stats['vacancy_ratio'] * 100:.1f}%)")
        print(f"Параметр alpha: {stats['alpha']}")
        print(f"Макс. радиус поиска: {stats['max_radius']}")
        print(f"Выполнено шагов симуляции: {stats['num_steps_simulated']}")
        print(f"Совершено перемещений: {stats['num_moves_made']}")

    # ================================================================
    # ВЕРОЯТНОСТИ ПЕРЕМЕЩЕНИЯ
    # ================================================================

    def compute_transition_probabilities(self, particle_pos, vacancies):
        """
        Вычисляет вероятности перемещения частицы в вакансии.

        Закон: p ~ 1/r^alpha, нормированный по всем вакансиям в радиусе.

        Аргументы:
            particle_pos: координаты частицы (массив длины 3)
            vacancies: массив координат вакансий (shape: M x 3)

        Возвращает:
            Список кортежей (vacancy_pos, distance, probability)
            Сумма вероятностей = 1 (если есть вакансии в радиусе)
        """
        distances = []
        valid_vacancies = []

        for v in vacancies:
            # Евклидово расстояние
            r = np.sqrt(np.sum((particle_pos - v) ** 2))
            # Исключаем саму частицу (r=0) и вакансии вне радиуса
            if 0 < r <= self.max_radius:
                distances.append(r)
                valid_vacancies.append(v)

        if len(distances) == 0:
            return []

        # Вероятность ~ 1/r^alpha
        weights = np.array([1.0 / (r ** self.alpha) for r in distances])
        probs = weights / weights.sum()  # нормировка

        return [
            (v, r, p)
            for v, r, p in zip(valid_vacancies, distances, probs)
        ]

    # ================================================================
    # СИМУЛЯЦИЯ
    # ================================================================

    def simulate_step(self):
        """
        Один шаг симуляции:
        1. Выбирается случайная частица
        2. Для неё вычисляются вероятности перемещения в вакансии
        3. Выбирается вакансия согласно вероятностям
        4. Частица перемещается

        Возвращает:
            (p_pos, v_pos, prob, r) — информация о перемещении,
            или None, если перемещение невозможно.
        """
        particles = self.get_particles()
        vacancies = self.get_vacancies()

        if len(particles) == 0 or len(vacancies) == 0:
            return None

        # Выбираем случайную частицу
        p_idx = np.random.randint(len(particles))
        p_pos = particles[p_idx]

        # Вычисляем вероятности для этой частицы
        probs_list = self.compute_transition_probabilities(p_pos, vacancies)

        if len(probs_list) == 0:
            return None

        # Выбираем вакансию согласно вероятностям
        probs = np.array([x[2] for x in probs_list])
        v_idx = np.random.choice(len(probs_list), p=probs)

        v_pos, r, prob = probs_list[v_idx]

        # Выполняем перемещение: частица -> вакансия, старое место -> вакансия
        self.lattice[tuple(p_pos)] = 0
        self.lattice[tuple(v_pos)] = 1

        # Сохраняем в историю
        self.history.append(self.lattice.copy())
        self.moves_history.append((p_pos.copy(), v_pos.copy(), prob, r))

        return p_pos.copy(), v_pos.copy(), prob, r

    def simulate_steps(self, num_steps, verbose=False):
        """
        Выполняет несколько шагов симуляции.

        Аргументы:
            num_steps: количество шагов
            verbose: выводить информацию о каждом шаге

        Возвращает:
            Список результатов всех шагов.
        """
        results = []
        for step in range(num_steps):
            result = self.simulate_step()
            results.append(result)

            if verbose:
                if result is not None:
                    p_pos, v_pos, prob, r = result
                    print(f"  Шаг {step + 1}: {p_pos} -> {v_pos}, "
                          f"p={prob:.4f}, r={r:.2f}")
                else:
                    print(f"  Шаг {step + 1}: нет доступных перемещений")

        return results

    # ================================================================
    # СОХРАНЕНИЕ / ЗАГРУЗКА СОСТОЯНИЯ
    # ================================================================

    def save_state(self, filepath):
        """
        Сохраняет текущее состояние решётки в файл.
        Нужно для передачи состояния между этапами.
        """
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        data = {
            'size': self.size,
            'particle_ratio': self.particle_ratio,
            'max_radius': self.max_radius,
            'alpha': self.alpha,
            'lattice': self.lattice.tolist(),
            'num_steps': len(self.history) - 1,
            'num_moves': len(self.moves_history)
        }

        with open(filepath, 'w') as f:
            json.dump(data, f)

        print(f"✓ Состояние сохранено в {filepath}")

    @classmethod
    def load_state(cls, filepath):
        """
        Загружает состояние решётки из файла.
        Метод класса — создаёт новый объект из сохранённых данных.
        """
        with open(filepath, 'r') as f:
            data = json.load(f)

        # Создаём объект без инициализации новой решётки
        lattice = cls.__new__(cls)
        lattice.size = data['size']
        lattice.particle_ratio = data['particle_ratio']
        lattice.max_radius = data['max_radius']
        lattice.alpha = data['alpha']
        lattice.lattice = np.array(data['lattice'])
        lattice.history = [lattice.lattice.copy()]
        lattice.moves_history = []

        print(f"✓ Состояние загружено из {filepath}")
        return lattice

    # ================================================================
    # УТИЛИТЫ
    # ================================================================

    def reset_history(self):
        """Очищает историю (полезно перед новым этапом симуляции)."""
        self.history = [self.lattice.copy()]
        self.moves_history = []

    def get_vacancy_distribution_by_layer(self, axis=2):
        """
        Возвращает распределение вакансий по слоям вдоль указанной оси.
        axis: 0=X, 1=Y, 2=Z
        """
        distribution = []
        for i in range(self.size):
            if axis == 0:
                layer = self.lattice[i, :, :]
            elif axis == 1:
                layer = self.lattice[:, i, :]
            else:
                layer = self.lattice[:, :, i]

            num_vacancies = np.sum(layer == 0)
            distribution.append(num_vacancies)

        return np.array(distribution)


# ================================================================
# ТЕСТ ПРИ ЗАПУСКЕ ФАЙЛА НАПРЯМУЮ
# ================================================================
if __name__ == '__main__':
    print("=" * 60)
    print("Тестирование класса MetalLattice")
    print("=" * 60)

    # Создаём решётку
    lattice = MetalLattice(size=10, particle_ratio=0.85,
                           max_radius=4, alpha=3, seed=42)

    print("\n--- Начальная статистика ---")
    lattice.print_statistics()

    # Тест вычисления вероятностей
    particles = lattice.get_particles()
    vacancies = lattice.get_vacancies()

    if len(particles) > 0 and len(vacancies) > 0:
        p0 = particles[0]
        probs = lattice.compute_transition_probabilities(p0, vacancies)
        print(f"\n--- Пример для частицы {p0} ---")
        print(f"Найдено вакансий в радиусе: {len(probs)}")
        if len(probs) > 0:
            sorted_probs = sorted(probs, key=lambda x: -x[2])
            print("Топ-3 наиболее вероятных перемещения:")
            for v, r, p in sorted_probs[:3]:
                print(f"  -> {v}, r={r:.2f}, p={p:.3f}")
            print(f"Сумма вероятностей: {sum(x[2] for x in probs):.4f}")

    # Тест симуляции
    print("\n--- Симуляция 5 шагов ---")
    lattice.simulate_steps(5, verbose=True)

    print("\n--- Статистика после симуляции ---")
    lattice.print_statistics()

    # Тест сохранения/загрузки
    lattice.save_state('test_state.json')
    loaded = MetalLattice.load_state('test_state.json')
    print("\n--- Статистика загруженной решётки ---")
    loaded.print_statistics()

    # Проверка идентичности
    assert np.array_equal(lattice.lattice, loaded.lattice), "Решётки не совпадают!"
    print("\n✓ Тест пройден: решётки идентичны")

    # Удаление тестового файла
    Path('test_state.json').unlink()
    print("✓ Тестовый файл удалён")