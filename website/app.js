"use strict";
const titles = {download:'Файлы проекта', launcher:'Лаунчер', login:'Вход в аккаунт', register:'Создать аккаунт', server:'Свой сервер'};
const dialog = document.getElementById('dialog');
document.querySelectorAll('[data-dialog]').forEach(button => {
  button.addEventListener('click', () => {
    const title = titles[button.dataset.dialog];
    document.getElementById('dialog-text').textContent = button.dataset.dialog === 'download' ? 'Файлы подключения выдаются через лаунчер.' : 'Ссылка скоро появится.';
    if (!title) return;
    document.getElementById('dialog-title').textContent = title;
    dialog.showModal();
  });
});
document.getElementById('close-dialog').addEventListener('click', () => dialog.close());
dialog.addEventListener('click', event => {
  const bounds = dialog.getBoundingClientRect();
  if (event.target === dialog && (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom)) dialog.close();
});
