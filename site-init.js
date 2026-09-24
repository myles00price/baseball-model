/* Run in the head: don't paint the legacy layout while routes initialize. */
document.documentElement.classList.add('board-boot');
setTimeout(()=>document.documentElement.classList.remove('board-boot'),3000);
