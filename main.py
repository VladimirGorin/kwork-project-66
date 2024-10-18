from telethon import TelegramClient, errors, events, functions
from config import SESSIONS_FOLDER, LOGGER_FILE, BAD_SESSIONS_FILE, MAILING_MESSAGES, AUTO_REPLY_MESSAGES, TARGET_GROUPS
import os, json, random, asyncio, logging

class TelegramSessionManager:
    def __init__(self):
        self.accounts = self.load_accounts()
        self.logger = self.setup_logger()

    def setup_logger(self):
        logger = logging.getLogger("TelegramBot")
        logger.setLevel(logging.DEBUG)

        file_handler = logging.FileHandler(LOGGER_FILE)
        console_handler = logging.StreamHandler()

        file_handler.setLevel(logging.DEBUG)
        console_handler.setLevel(logging.INFO)

        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

        return logger

    def load_accounts(self):
        accounts = []
        for file in filter(lambda f: f.endswith(".json"), os.listdir(SESSIONS_FOLDER)):
            phone = file.replace(".json", "")
            json_path = os.path.join(SESSIONS_FOLDER, file)
            session_path = os.path.join(SESSIONS_FOLDER, f"{phone}.session")

            with open(json_path, 'r') as json_file:
                data = json.load(json_file)

            accounts.append({
                'phone': phone,
                'session': session_path,
                'api_id': data['app_id'],
                'api_hash': data['app_hash'],
                'proxy': data.get('proxy')
            })
        return accounts

    async def validate_session(self, account):
        try:
            client = TelegramClient(account['session'], account['api_id'], account['api_hash'])
            await client.connect()

            if not await client.is_user_authorized():
                raise errors.UnauthorizedError("Сессия не авторизована")

            await client.disconnect()
            return True

        except Exception as e:
            self.handle_invalid_session(account, e)
            return False

    def handle_invalid_session(self, account, exception):
        self.logger.error(f"(Account: {account['phone']}) Невалидная сессия: {exception}")
        with open(BAD_SESSIONS_FILE, 'a') as f:
            f.write(f"{account['phone']}\n")

        self.remove_session_files(account)

    def remove_session_files(self, account):
        session_json_file = account["session"].replace('.session', '.json')
        for path in (account["session"], session_json_file):
            if os.path.exists(path):
                os.remove(path)

    async def send_message(self, client, target_group, message, phone):
        await client.send_message(target_group, message)
        self.logger.info(f"(Account: {phone}) Сообщение отправлено в {target_group}")

    async def auto_reply(self, client, phone):
        @client.on(events.NewMessage(incoming=True))
        async def handler(event):
            await self.handle_new_message(event, phone)

    async def handle_new_message(self, event, phone):
        try:
            if event.is_private:
                sender = await event.get_sender()
                reply_message = random.choice(AUTO_REPLY_MESSAGES)
                await event.respond(reply_message)
                self.logger.info(f"(Account: {phone}) Ответил пользователю {sender.id} с текстом: {reply_message}")
        except errors.FloodWaitError as e:
            await self.handle_flood_wait(e, phone)
        except errors.ChatWriteForbiddenError:
            self.logger.error(f"(Account: {phone}) Ошибка прав доступа")
        except Exception as e:
            self.logger.error(f"(Account: {phone}) Ошибка автоответчика: {e}")

    async def handle_flood_wait(self, error, phone):
        self.logger.warning(f"(Account: {phone}) Ожидание {error.seconds} секунд из-за ограничения")
        await asyncio.sleep(error.seconds)

    async def distribute_messages(self, client, target_groups, phone, interval=3600):
        while True:
            for group in target_groups:
                calc_sleep_time = interval // self.valid_accounts_count
                await self.send_group_message(client, group, phone, interval)

                self.logger.info(f"(Account: {phone}) Ожидание {calc_sleep_time} секунд перед следующей рассылкой")
                await asyncio.sleep(calc_sleep_time)

    async def send_group_message(self, client, group, phone, interval):
        try:
            message = random.choice(MAILING_MESSAGES)
            await client(functions.channels.JoinChannelRequest(group))
            await self.send_message(client, group, message, phone)

        except errors.FloodWaitError as e:
            await self.handle_flood_wait(e, phone)
        except errors.ChatWriteForbiddenError:
            self.logger.error(f"(Account: {phone}) Ошибка прав доступа")
        except Exception as e:
            self.logger.error(f"(Account: {phone}) Ошибка распределения сообщений: {e}")

    async def start_account_session(self, account):
        try:
            client = self.create_client(account)
            await client.start()

            await self.auto_reply(client, account['phone'])
            await self.distribute_messages(client, TARGET_GROUPS, account['phone'])

        except Exception as e:
            self.logger.error(f"(Account: {account['phone']}) Ошибка подключения сессии: {e}")

    def create_client(self, account):
        proxy = None
        if account['proxy']:
            if type(account["proxy"]) != list:
                proxy = {
                    'proxy_type': 'socks5',
                    'addr': account['proxy'].split(':')[0],
                    'port': int(account['proxy'].split(':')[1]),
                    'username': account['proxy'].split(':')[2],
                    'password': account['proxy'].split(':')[3],
                }


        return TelegramClient(account['session'], account['api_id'], account['api_hash'], proxy=proxy)

    async def run(self):
        tasks = [asyncio.create_task(self.start_account_session(account)) for account in self.accounts if await self.validate_session(account)]
        self.valid_accounts_count = len(tasks)
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        manager = TelegramSessionManager()
        asyncio.run(manager.run())
    except KeyboardInterrupt:
        print("Пока :)")
