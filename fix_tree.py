import os

views_dir = 'c:/odoo-custom-addons/hudson_subscriptions/views'
for root, dirs, files in os.walk(views_dir):
    for f in files:
        if f.endswith('.xml'):
            filepath = os.path.join(root, f)
            with open(filepath, 'r', encoding='utf-8') as file:
                content = file.read()
            
            content = content.replace('<tree ', '<list ')
            content = content.replace('<tree>', '<list>')
            content = content.replace('</tree>', '</list>')
            content = content.replace('"tree,', '"list,')
            content = content.replace(',tree,', ',list,')
            content = content.replace(',tree"', ',list"')
            content = content.replace("'tree'", "'list'")
            content = content.replace('"tree"', '"list"')
            
            with open(filepath, 'w', encoding='utf-8') as file:
                file.write(content)
print('Replaced tree with list in all XML files.')
