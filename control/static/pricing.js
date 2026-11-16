// Period switch for the pricing cards: the server renders every number, this only shows the chosen period.
(function(){var wrap=document.querySelector('.tiers-wrap');if(!wrap)return;var tabs=wrap.querySelectorAll('.period button');if(!tabs.length)return;
function show(key){wrap.dataset.period=key;tabs.forEach(function(b){var on=b.dataset.period===key;b.classList.toggle('on',on);b.setAttribute('aria-pressed',on?'true':'false')});
 wrap.querySelectorAll('.tier').forEach(function(card){var f;try{f=JSON.parse(card.dataset.prices)[key]}catch(e){return}if(!f)return;
  card.querySelector('.js-per').textContent=f.per;card.querySelector('.js-line').textContent=f.line;card.querySelector('.js-strip').innerHTML=f.strip;
  var s=card.querySelector('.js-save');s.textContent=f.badge;s.hidden=!f.badge;
  var a=card.querySelector('.js-cta');a.href='/rejestracja?plan='+encodeURIComponent(card.dataset.slug)+'&period='+encodeURIComponent(key)})}
tabs.forEach(function(b){b.addEventListener('click',function(){show(b.dataset.period)})});show(wrap.dataset.period||'1')})();
