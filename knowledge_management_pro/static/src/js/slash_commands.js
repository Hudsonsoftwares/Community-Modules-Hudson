/** @odoo-module **/

export const slashCommands = [
    { title: 'Heading 1', command: '/heading', icon: 'H1' },
    { title: 'Checklist', command: '/checklist', icon: '☑' },
    { title: 'Separator', command: '/separator', icon: '---' },
    { title: 'Text', command: '/text', icon: 'T' },
    { title: 'Bullet List', command: '/bullet', icon: '•' },
    { title: 'Numbered List', command: '/numbered', icon: '1.' },
    { title: 'Table', command: '/table', icon: '▦' },
    { title: 'Image', command: '/image', icon: '🖼' },
    { title: 'File', command: '/file', icon: '📎' },
    { title: 'Link', command: '/link', icon: '🔗' },
    { title: 'Quote', command: '/quote', icon: '”' },
    { title: 'Code Block', command: '/code', icon: '</>' },
    { title: 'Note', command: '/note', icon: '💡' },
    { title: 'Warning', command: '/warning', icon: '⚠' },
    { title: 'Video', command: '/video', icon: '▶' },
    { title: 'Link Article', command: '/article', icon: '📄' },
    { title: 'Calendar', command: '/calendar', icon: '📅' }
];

export function handleSlashCommand(command) {
    console.log(`Executed command: ${command}`);
    // Future implementation of slash command logic using Odoo wysiwyg or custom editor
}
