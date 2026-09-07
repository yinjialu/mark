import {createMarksUI} from './codex-marks-library.js';

export function createMarkSidebar(ui){
  const {React,jsx,useNavigate,useLocation}=ui;
  const Library=createMarksUI(React,jsx,ui);
  function Icon(props){return jsx.jsx('svg',{viewBox:'0 0 24 24',width:24,height:24,fill:'none',stroke:'currentColor',strokeWidth:1.6,strokeLinecap:'round',strokeLinejoin:'round','aria-hidden':true,...props,children:jsx.jsx('path',{d:'M6 20V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v15l-6-4-6 4Z'})});}
  function Page(){
    const navigate=useNavigate(),{state}=useLocation();
    return jsx.jsx(Library,{page:true,navigate,sourceThreadId:state?.markSourceThreadId,selectedId:state?.markSelectedId,initialNotice:state?.markNotice});
  }
  function useItem(){
    const navigate=useNavigate(),{pathname}=useLocation();
    const sourceThreadId=pathname.match(/^\/local\/([0-9a-f-]{36})(?:\/|$)/i)?.[1];
    return {id:'builtin:mark',label:'mark',icon:Icon,railIcon:jsx.jsx(Icon,{}),visibleByDefault:true,onSelect:()=>navigate('/mark',{state:{markSourceThreadId:sourceThreadId}}),isCurrentDestination:pathname==='/mark',hasUnreadActivity:false};
  }
  return {Page,useItem};
}
