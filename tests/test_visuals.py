"""Validate real vector resources without replacing icons by widget mocks."""
import ast
from pathlib import Path
import unittest
from tunplayer.visuals import ICONS,icon_pixbuf


class IconResources(unittest.TestCase):
    def test_search_icon_used_by_subtitle_dialog_is_present_and_decodes(self):
        pixbuf=icon_pixbuf('search',18)
        self.assertEqual((pixbuf.get_width(),pixbuf.get_height()),(18,18))

    def test_every_registered_icon_decodes_with_the_real_svg_loader(self):
        for name in ICONS:
            with self.subTest(icon=name):self.assertGreater(icon_pixbuf(name,24).get_width(),0)

    def test_literal_button_and_icon_references_exist(self):
        def names(node):
            if isinstance(node,ast.Constant) and isinstance(node.value,str):return [node.value]
            if isinstance(node,ast.IfExp):return names(node.body)+names(node.orelse)
            return []
        for path in (Path(__file__).resolve().parents[1]/'tunplayer').glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                if not isinstance(node,ast.Call):continue
                function=node.func.id if isinstance(node.func,ast.Name) else ''
                references=[]
                if function in ('icon','icon_pixbuf') and node.args:references+=names(node.args[0])
                if function=='button':
                    for keyword in node.keywords:
                        if keyword.arg=='symbol':references+=names(keyword.value)
                if function=='navigation' and len(node.args)>1:references+=names(node.args[1])
                for name in references:
                    with self.subTest(file=path.name,line=node.lineno,icon=name):self.assertIn(name,ICONS)
