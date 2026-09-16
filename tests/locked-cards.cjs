const vm=require('vm'),fs=require('fs'),assert=require('assert/strict');
class El{constructor(tag,cls='',text=''){this.tag=tag;this.className=cls;this.text=text;this.children=[];}append(...xs){this.children.push(...xs)}replaceChildren(x){this.children=x.children;this.count=(this.count||0)+1}querySelector(){return this.children.length?this.children[0]:null}get content(){return this.text+this.children.map(x=>x.content).join(' ');}}
const row={Flag:'BET',Away:'Seattle Mariners',Home:'Los Angeles Angels','Game#':'2',GamePk:'42','DK Away Odds':'-169','Model Away%':'69.1'};
function run({bet=true,lock=true,odds='-169',live={},team='Seattle Mariners'}={}){
 const grid=new El('div');const ctx={sport:'mlb',picks:[{...row,Flag:bet?'BET':'PASS','DK Away Odds':odds}],locked:new Set(lock?['Seattle Mariners@Los Angeles Angels#2']:[]),liveMap:live,playerArt:{1:{name:'Player',team,approved:true,src:'assets/player-art/1.png'}},roster:[{id:1,t:136}],TID:{'Seattle Mariners':136},assetBase:'https://example.com/',URL,document:{getElementById:()=>grid,createDocumentFragment:()=>new El('fragment')},make:(...a)=>new El(...a),logo:()=>'',flagged_side_js:()=> 'away',whyText:()=> 'Reason'};
 vm.createContext(ctx);vm.runInContext(fs.readFileSync(require('path').join(__dirname,'../vegas.js'),'utf8').split('    // A notified key alone')[1].split('    function enhance(){')[0].replace(/^.*\n/,'')+'\nrenderFeaturedPlays();renderFeaturedPlays();',ctx);return grid;
}
assert.match(run().content,/LOCKED · OFFICIAL PLAY/);assert.match(run().content,/59.17/);assert.equal(run().count,1);
assert.equal(run({bet:false}).children.length,0);
assert.match(run({lock:false}).content,/LEAN · NOT LOCKED/);
assert.match(run({odds:'+150'}).content,/150.00/);
assert.match(run({odds:''}).content,/Unavailable/);
assert.doesNotMatch(run({team:'Other team'}).content,/FEATURED/);
assert.match(run({live:{first:{pk:41,state:'Final',as:1,hs:0},second:{pk:42,state:'Final',as:0,hs:2}}}).content,/LOCKED · LOST/);
assert.doesNotMatch(run({live:{first:{pk:41,state:'Final',as:1,hs:0}}}).content,/CASHED/);
assert.doesNotMatch(run({live:{second:{pk:42,state:'Final',as:2,hs:2}}}).content,/CASHED|LOST/);
console.log('Passed: official/lean state, skipped games, prices, missing odds, team identity, doubleheader matching, ties and stable rerender.');
