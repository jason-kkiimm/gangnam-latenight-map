// 화면: 구글 지도 + 목록. 서버(/api/nearby)가 계산한 결과를 보여주기만 하고 저장하지 않는다.
const { station, cooldown } = window.APP;
const $ = (id) => document.getElementById(id);

let map = null;
let markers = [];
let infoWindow = null;
let busy = false;

function initMap() {
  map = new google.maps.Map($("map"), {
    center: station,
    zoom: 16,
    mapTypeControl: false,
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

function render(places, origin) {
  const list = $("list");
  list.textContent = "";
  clearMarkers();

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

async function search(origin, note) {
  if (busy) return;
  busy = true;
  setStatus("조회 중…");
  try {
    const q = new URLSearchParams({ lat: origin.lat, lng: origin.lng, type: selectedType() });
    const res = await fetch("/api/nearby?" + q);
    const data = await res.json();
    if (!res.ok) {
      setStatus(data.error || "조회에 실패했습니다.");
      if (data.retry_after) lockButtons(Math.ceil(data.retry_after));
      return;
    }
    render(data.places, origin);
    setStatus(
      data.count
        ? `${note} 반경 1km 안 지금 영업 중 ${data.count}곳, 가까운 순`
        : `${note} 반경 1km 안에 지금 영업 중인 곳이 없습니다.`
    );
    lockButtons(cooldown);
  } catch (e) {
    setStatus("서버에 연결하지 못했습니다.");
  } finally {
    busy = false;
  }
}

$("btn-station").addEventListener("click", () => search(station, "강남역 기준."));

$("btn-here").addEventListener("click", () => {
  if (!navigator.geolocation) {
    setStatus("이 브라우저는 위치를 지원하지 않습니다. 강남역 기준으로 보여줍니다.");
    search(station, "(위치 없음, 강남역 기준)");
    return;
  }
  setStatus("위치 확인 중…");
  navigator.geolocation.getCurrentPosition(
    (pos) => search({ lat: pos.coords.latitude, lng: pos.coords.longitude }, "내 위치 기준."),
    () => {
      setStatus("위치를 받지 못해 강남역 기준으로 보여줍니다.");
      search(station, "(위치 거부, 강남역 기준)");
    },
    { timeout: 10000 }
  );
});
