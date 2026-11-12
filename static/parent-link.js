(()=>{const input=document.getElementById('parent-credential');if(input&&location.hash){input.value=location.hash.slice(1);history.replaceState(null,'',location.pathname+location.search);}})();
