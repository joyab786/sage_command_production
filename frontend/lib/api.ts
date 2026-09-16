export async function fetchSage(endpoint: string) {
  const token = localStorage.getItem("sage_token") || "manager_token";
  const res = await fetch(`http://localhost:8000${endpoint}`, {
    headers: {
      "Authorization": `Bearer ${token}`
    }
  });
  if (!res.ok) {
    throw new Error(`API error: ${res.status}`);
  }
  return res.json();
}
