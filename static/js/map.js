// 화면: 구글 지도 + 목록. 서버(/api/nearby)가 계산한 결과를 보여주기만 하고 저장하지 않는다.
const { station, cooldown } = window.APP;
const $ = (id) => document.getElementById(id);

let map = null;
let markers = [];
let infoWindow = null;
let busy = false;
let last = null; // 마지막으로 받은 결과 { places, origin, note }. 화면에서만 쓰고 저장하지 않는다.

function initMap() {
  map = new google.maps.Map($("map"), {
    center: station,
    zoom: 16,
    mapTypeControl: false,
    // 기본 가게·상업시설(POI) 아이콘만 숨겨 우리 마커가 눈에 띄게 한다.
    // 교통(지하철역 등)과 도로 이름은 건드리지 않는다. 구글 로고·저작권 표시는 스타일로 가려지지 않으며, 가리면 안 된다.
    // mapId를 쓰면 이 styles 설정은 무시된다(클라우드 스타일링을 써야 함). 지금은 mapId 없음.
    styles: [
      { featureType: "poi.business", stylers: [{ visibility: "off" }] },
      { featureType: "poi", elementType: "labels.icon", stylers: [{ visibility: "off" }] },
    ],
  });
  infoWindow = new google.maps.InfoWindow();
}
window.initMap = initMap;

// 키가 없으면 지도 없이 목록만 쓴다.
window.addEventListener("load", () => {
  if (!document.querySelector('script[src*="maps.googleapis.com"]')) {
    $("map").innerHTML =
      '<div class="no-map">지도 키(GOOGLE_MAPS_BROWSER_KEY)가 설정되지 않아 지도를 표시하지 않습니다. 목록은 그대로 동작합니다.</div>';
  }
});

function setStatus(text) {
  $("status").textContent = text;
}

const TYPE_LABEL = { restaurant: "음식점", cafe: "카페" };

function selectedType() {
  return document.querySelector('input[name="type"]:checked').value;
}

function closingText(p) {
  if (p.is_24h) return "24시간 영업";
  if (p.closes_at == null) return "마감 시각 확인 필요";
  return "오늘 마감 " + (p.closes_next_day ? "다음날 " : "") + p.closes_at;
}

function kakaoUrl(name) {
  // API 호출 없이 주소만 만든다.
  return "https://map.kakao.com/link/search/" + encodeURIComponent(name);
}

function clearMarkers() {
  markers.forEach((m) => m.setMap(null));
  markers = [];
}

function render(places, origin, emptyMessage) {
  const list = $("list");
  list.textContent = "";
  clearMarkers();

  // 보여줄 곳이 0곳이면 목록 자리에 이유를 적어, 고장으로 오해하지 않게 한다.
  if (!places.length && emptyMessage) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = emptyMessage;
    list.append(li);
  }

  if (map) {
    const bounds = new google.maps.LatLngBounds();
    bounds.extend(origin);
    markers.push(
      new google.maps.Marker({
        map,
        position: origin,
        title: "기준 위치",
        icon: {
          path: google.maps.SymbolPath.CIRCLE,
          scale: 7,
          fillColor: "#1a73e8",
          fillOpacity: 1,
          strokeColor: "#fff",
          strokeWeight: 2,
        },
      })
    );
    places.forEach((p, i) => {
      const position = { lat: p.lat, lng: p.lng };
      const marker = new google.maps.Marker({ map, position, title: p.name, label: String(i + 1) });
      marker.addListener("click", () => {
        const box = document.createElement("div");
        const strong = document.createElement("strong");
        strong.textContent = p.name;
        box.append(strong, document.createElement("br"), document.createTextNode(closingText(p)));
        infoWindow.setContent(box);
        infoWindow.open(map, marker);
      });
      markers.push(marker);
      bounds.extend(position);
    });
    if (places.length) map.fitBounds(bounds, 40);
    else map.setCenter(origin);
  }

  places.forEach((p, i) => {
    const li = document.createElement("li");

    const name = document.createElement("div");
    name.className = "name";
    name.textContent = `${i + 1}. ${p.name}`;
    if (p.late_night) {
      const b = document.createElement("span");
      b.className = "badge";
      b.textContent = "심야";
      name.append(b);
    }

    const info = document.createElement("div");
    info.textContent = `${p.distance_m}m · ${closingText(p)}`;

    const links = document.createElement("div");
    for (const [label, href] of [
      ["구글 지도", p.google_maps_url],
      ["카카오맵에서 검색", kakaoUrl(p.name)],
    ]) {
      if (!href) continue;
      const a = document.createElement("a");
      a.href = href;
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = label;
      a.addEventListener("click", (e) => e.stopPropagation());
      links.append(a);
    }

    li.append(name, info, links);
    li.addEventListener("click", () => {
      if (map) map.panTo({ lat: p.lat, lng: p.lng });
    });
    list.append(li);
  });
}

function lockButtons(seconds) {
  const buttons = [$("btn-here"), $("btn-station")];
  buttons.forEach((b) => (b.disabled = true));
  setTimeout(() => buttons.forEach((b) => (b.disabled = false)), seconds * 1000);
}

// 이미 받은 결과를 다시 그린다. "심야만 보기"는 서버를 다시 부르지 않고 여기서만 거른다.
function showLast() {
  if (!last) return;
  const lateOnly = $("late-only").checked;
  const shown = lateOnly ? last.places.filter((p) => p.late_night === true) : last.places;
  const total = last.places.length;
  render(
    shown,
    last.origin,
    !total
      ? "반경 1km 안에 지금 영업 중인 곳이 없어요."
      : '자정을 넘겨 닫는 곳이 없어요. "심야만 보기"를 끄면 지금 영업 중인 곳을 볼 수 있어요.'
  );
  const kind = TYPE_LABEL[last.type] || "가게"; // 지금 보이는 결과의 종류(음식점/카페)
  if (!total) {
    setStatus(`${last.note} 반경 1km 안에 지금 영업 중인 ${kind}이(가) 없어요.`);
  } else if (lateOnly) {
    setStatus(
      shown.length
        ? `${last.note} 지금 영업 중인 ${kind} ${total}곳 중 심야(자정을 넘겨 닫는 곳) ${shown.length}곳, 가까운 순`
        : `${last.note} 지금 영업 중인 ${kind} ${total}곳 중 심야인 곳이 없어요. "심야만 보기"를 끄면 전체가 보여요.`
    );
  } else {
    setStatus(`${last.note} 반경 1km 안 지금 영업 중인 ${kind} ${total}곳, 가까운 순`);
  }
  applyStale();
}

// 라디오(음식점/카페)를 바꿨는데 아직 다시 찾지 않았으면, 옛 목록·마커를 흐리게 하고 안내한다.
// 서버를 부르지 않는다. 기준 위치 마커(markers[0])는 흐리게 하지 않는다. 구글 로고·저작권 표시는 건드리지 않는다.
function applyStale() {
  const stale = !!last && last.type !== selectedType();
  $("list").classList.toggle("stale", stale);
  markers.forEach((m, i) => m.setOpacity(i > 0 && stale ? 0.35 : 1));
  if (stale) setStatus("종류가 바뀌었어요. 버튼을 눌러 다시 찾아주세요.");
}

$("late-only").addEventListener("change", showLast);
document.querySelectorAll('input[name="type"]').forEach((r) => r.addEventListener("change", showLast));

async function search(origin, note) {
  if (busy) return;
  busy = true;
  setStatus("조회 중…");
  const type = selectedType(); // 보낸 종류를 기억해 둔다. 조회 중에 라디오를 바꿔도 결과의 종류가 틀어지지 않게.
  try {
    const q = new URLSearchParams({ lat: origin.lat, lng: origin.lng, type });
    const res = await fetch("/api/nearby?" + q);
    const data = await res.json();
    if (!res.ok) {
      setStatus(data.error || "조회에 실패했어요.");
      if (data.retry_after) lockButtons(Math.ceil(data.retry_after));
      return;
    }
    last = { places: data.places, origin, note, type };
    showLast();
    lockButtons(cooldown);
  } catch (e) {
    setStatus("서버에 연결하지 못했어요.");
  } finally {
    busy = false;
  }
}

$("btn-station").addEventListener("click", () => search(station, "강남역 기준."));

$("btn-here").addEventListener("click", () => {
  if (!navigator.geolocation) {
    setStatus("이 브라우저는 위치를 지원하지 않아요. 강남역 기준으로 보여줄게요.");
    search(station, "(위치 없음, 강남역 기준)");
    return;
  }
  setStatus("위치 확인 중…");
  navigator.geolocation.getCurrentPosition(
    (pos) => search({ lat: pos.coords.latitude, lng: pos.coords.longitude }, "내 위치 기준."),
    () => {
      setStatus("위치를 받지 못해서 강남역 기준으로 보여줄게요.");
      search(station, "(위치 거부, 강남역 기준)");
    },
    { timeout: 10000 }
  );
});
