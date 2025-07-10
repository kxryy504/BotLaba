# promote.py
from models import SessionLocal, User

def promote(user_id: int):
    session = SessionLocal()
    user = session.query(User).get(user_id)
    if not user:
        print(f"Пользователь с id={user_id} не найден")
    else:
        user.is_admin = True
        session.commit()
        print(f"Пользователь {user.full_name} (id={user.id}) теперь админ")
    session.close()

if __name__ == '__main__':
    promote(1)
