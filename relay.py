import os
import subprocess
import time


def get_relay_state(relay_id: str) -> bool:
    # Запуск usbrelay без аргументов возвращает список всех реле и их состояния
    result = subprocess.run(
        ["usbrelay"], capture_output=True, text=True, check=True
    )
    return f"{relay_id}=1" in result.stdout


def set_relay(relay_id: str, state: bool) -> None:
    val = 1 if state else 0
    subprocess.run(
        ["usbrelay", f"{relay_id}={val}"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


if __name__ == "__main__":
    RELAY_ID = os.getenv("RELAY_ID", "959BI_1")

    print(f"Запуск 10 циклов проверки для {RELAY_ID} с паузой 5 секунд:")

    for i in range(1, 11):
        set_relay(RELAY_ID, True)
        state_on = get_relay_state(RELAY_ID)
        print(
            f"Цикл {i:2d}/10 | Подана команда: ВКЛ  | Ответ от реле: {'ВКЛ (1)' if state_on else 'ВЫКЛ (0)'}"
        )
        time.sleep(5)

        set_relay(RELAY_ID, False)
        state_off = get_relay_state(RELAY_ID)
        print(
            f"Цикл {i:2d}/10 | Подана команда: ВЫКЛ | Ответ от реле: {'ВКЛ (1)' if state_off else 'ВЫКЛ (0)'}"
        )
        time.sleep(5)

    print("Тестирование завершено.")


# import subprocess
# import time


# def set_relay(state: bool) -> None:
#     val = 1 if state else 0
#     subprocess.run(["usbrelay", f"959BI_1={val}"], check=True)


# if __name__ == "__main__":
#     set_relay(True)   # Включить
#     time.sleep(5)     # Пауза 5 секунд
#     set_relay(False)  # Выключить