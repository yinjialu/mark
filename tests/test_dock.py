from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'integration'))
from dock import updated_tiles, tile_path

class DockTests(unittest.TestCase):
    def setUp(self):
        self.state=Path('/tmp/mark-dock-test').resolve()
        self.old=self.state/'builds/old/Codex mark.app'
        self.new=self.state/'builds/new/ChatGPT mark.app'
        self.official=Path('/Applications/ChatGPT.app')
    def tile(self,path):
        return {'tile-type':'file-tile','tile-data':{'file-label':path.stem,'book':b'old-bookmark','file-data':{'_CFURLString':path.as_uri()+'/'}}}
    def test_unify_preserves_position_and_other_apps(self):
        other=self.tile(Path('/Applications/Other.app'))
        tiles=[other,self.tile(self.official),self.tile(self.old)]
        result=updated_tiles(tiles,self.state,self.new,self.official)
        self.assertEqual(len(result),2)
        self.assertEqual(result[0],other)
        self.assertEqual(tile_path(result[1]),self.new)
        self.assertNotIn('book',result[1]['tile-data'])
        self.assertEqual(tile_path(tiles[1]),self.official)
    def test_upgrade_updates_only_managed_tiles(self):
        official=self.tile(self.official)
        result=updated_tiles([official,self.tile(self.old)],self.state,self.new)
        self.assertEqual(result[0],official)
        self.assertEqual(tile_path(result[1]),self.new)
        self.assertEqual(updated_tiles([official],self.state,self.new),[official])
    def test_explicit_unify_can_add_missing_entry(self):
        result=updated_tiles([],self.state,self.new,self.official)
        self.assertEqual(tile_path(result[0]),self.new)
