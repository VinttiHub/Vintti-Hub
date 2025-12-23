function LogoutFab() {
  const handleLogout = () => {
    if (typeof window === 'undefined') return;
    window.localStorage.removeItem('user_email');
    window.localStorage.removeItem('user_id');
    window.localStorage.removeItem('user_id_owner_email');
    window.localStorage.removeItem('user_avatar');
    window.sessionStorage.clear();
    window.location.href = '/';
  };

  return (
    <button type="button" className="logout-fab" id="logoutFab" onClick={handleLogout} title="Log out">
      <i className="fa-solid fa-right-from-bracket" aria-hidden="true" />
      <span>Log out</span>
    </button>
  );
}

export default LogoutFab;
