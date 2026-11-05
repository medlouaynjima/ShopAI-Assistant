"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

type Product = {
  sku: string;
  name: string;
  category: string;
  description: string;
  price: number;
  inventory: number;
};

type OrderItem = {
  product_name: string;
  sku: string;
  quantity: number;
  price: number;
};

type Order = {
  order_id: string;
  status: string;
  total: number;
  created_at: string;
  tracking_number: string | null;
  items: OrderItem[];
};

type CheckoutOrder = Order;

type CartLine = { product: Product; quantity: number };

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  pendingCancellation?: { cancellation_id: string; order_id: string };
};

type ApiError = { detail?: string };
type Section = "shop" | "orders" | "account";
type AuthMode = "login" | "register" | "verify";

async function apiRequest<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`/api/backend/${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { "content-type": "application/json" } : {}),
      ...init?.headers,
    },
    cache: "no-store",
  });
  const payload = (await response.json().catch(() => ({}))) as T & ApiError;
  if (!response.ok) {
    throw new Error(payload.detail || `Request failed (${response.status}).`);
  }
  return payload;
}

export default function ShopAssistApp() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [customerName, setCustomerName] = useState("");
  const [activeSection, setActiveSection] = useState<Section>("shop");
  const [supportPrompt, setSupportPrompt] = useState("");
  const [chatOpen, setChatOpen] = useState(false);
  const [authDialogOpen, setAuthDialogOpen] = useState(false);
  const [cartOpen, setCartOpen] = useState(false);
  const [checkoutOpen, setCheckoutOpen] = useState(false);
  const [checkoutOrder, setCheckoutOrder] = useState<CheckoutOrder | null>(null);
  const [cart, setCart] = useState<CartLine[]>([]);
  const [cartHydrated, setCartHydrated] = useState(false);
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [verificationEmail, setVerificationEmail] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const loadProfile = useCallback(async () => {
    try {
      const profile = await apiRequest<{ full_name: string; email: string }>(
        "auth/me",
      );
      setCustomerName(profile.full_name);
      setAuthenticated(true);
    } catch {
      setAuthenticated(false);
    }
  }, []);

  useEffect(() => {
    void loadProfile();
  }, [loadProfile]);

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem("morrow-cart-v1");
      if (saved) setCart(JSON.parse(saved) as CartLine[]);
    } catch {
      window.localStorage.removeItem("morrow-cart-v1");
    } finally {
      setCartHydrated(true);
    }
  }, []);

  useEffect(() => {
    if (!cartHydrated) return;
    window.localStorage.setItem("morrow-cart-v1", JSON.stringify(cart));
  }, [cart, cartHydrated]);

  const clearAlerts = () => {
    setError("");
    setNotice("");
  };
  const clearError = useCallback(() => setError(""), []);

  async function handleSignOut() {
    clearAlerts();
    try {
      await apiRequest<{ message: string }>("auth/logout", { method: "POST" });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not sign out.");
    } finally {
      setAuthenticated(false);
      setCustomerName("");
      setActiveSection("shop");
      setChatOpen(false);
    }
  }

  function openAuth(mode: AuthMode = "login") {
    clearAlerts();
    setAuthMode(mode);
    setAuthDialogOpen(true);
  }

  function openSupport(prompt = "") {
    setSupportPrompt(prompt);
    setChatOpen(true);
  }

  function addToBag(product: Product) {
    if (product.inventory < 1) return;
    setCart((current) => {
      const existing = current.find((line) => line.product.sku === product.sku);
      return existing
        ? current.map((line) => line.product.sku === product.sku
            ? { ...line, quantity: Math.min(line.quantity + 1, product.inventory) }
            : line)
        : [...current, { product, quantity: 1 }];
    });
    setNotice(`${product.name} added to your bag.`);
  }

  const bagCount = cart.reduce((sum, line) => sum + line.quantity, 0);
  const bagTotal = cart.reduce((sum, line) => sum + line.product.price * line.quantity, 0);

  function beginCheckout() {
    if (!authenticated) {
      openAuth("login");
      return;
    }
    setCheckoutOrder(null);
    setCartOpen(false);
    setCheckoutOpen(true);
  }

  return (
    <main className="site-shell">
      <header className="topbar">
        <a className="brand" href="#" onClick={() => setActiveSection("shop")} aria-label="Morrow home">
          <span className="brand-mark" aria-hidden="true"><BrandMark /></span>
          <span>morrow<span className="brand-period">.</span></span>
        </a>
        <nav className="main-nav" aria-label="Main navigation">
          <button className={`nav-link ${activeSection === "shop" ? "active" : ""}`} onClick={() => setActiveSection("shop")}>Shop all</button>
          <a className="nav-link nav-anchor" href="#catalog">New arrivals</a>
          {authenticated && <button className={`nav-link ${activeSection === "orders" ? "active" : ""}`} onClick={() => setActiveSection("orders")}>My orders</button>}
        </nav>
        <div className="customer-menu">
          {authenticated ? (
            <>
              <button className="account-trigger" onClick={() => setActiveSection("account")} aria-label="Open account"><span className="avatar">{customerName.slice(0, 1).toUpperCase()}</span><span className="customer-greeting">Hi, {customerName.split(" ")[0]}</span></button>
              <button className="text-button sign-out-button" onClick={() => void handleSignOut()}>Sign out</button>
            </>
          ) : (
            <>
              <button className="text-button sign-in-button" onClick={() => openAuth("login")}>Sign in</button>
              <button className="button primary create-account-button" onClick={() => openAuth("register")}>Create account</button>
            </>
          )}
          <button className="bag-button" onClick={() => setCartOpen(true)} aria-label={`Open shopping bag, ${bagCount} items`}>
            <BagIcon /><span>Bag</span><b>{bagCount}</b>
          </button>
        </div>
      </header>

      <section className="page-content">
        {notice && <div className="notice success">{notice}</div>}
        {error && <div className="notice error">{error}</div>}
        {activeSection === "shop" && (
          <ShopSection
            onError={setError}
            onClearError={clearError}
            onOpenSupport={openSupport}
            onAddToBag={addToBag}
          />
        )}
        {activeSection === "orders" && (
          <OrdersSection onError={setError} onClearError={clearError} />
        )}
        {activeSection === "account" && (
          <AccountSection
            onError={setError}
            onClearError={clearError}
            onOpenOrders={() => setActiveSection("orders")}
            onOpenSupport={() => openSupport()}
          />
        )}
      </section>
      <footer className="footer">
        <span>Considered essentials for the everyday.</span>
        <span>© 2026 Morrow Supply</span>
      </footer>
      {authenticated !== null && <button className="chat-launcher" onClick={() => setChatOpen((open) => !open)} aria-expanded={chatOpen} aria-label={chatOpen ? "Close support chat" : "Open support chat"}>
        {chatOpen ? <span className="launcher-close">×</span> : <><ChatIcon /><span className="launcher-label">Need a hand?</span><i /></>}
      </button>}
      {chatOpen && <div className="chat-widget"><SupportSection authenticated={Boolean(authenticated)} initialPrompt={supportPrompt} onError={setError} onClearError={clearError} onClose={() => setChatOpen(false)} /></div>}
      {cartOpen && (
        <div className="drawer-backdrop" onClick={() => setCartOpen(false)}>
          <aside className="bag-drawer" onClick={(event) => event.stopPropagation()} aria-label="Shopping bag">
            <div className="drawer-heading"><div><span className="eyebrow">YOUR SELECTION</span><h2>Your bag <span>({bagCount})</span></h2></div><button onClick={() => setCartOpen(false)} aria-label="Close bag">×</button></div>
            {cart.length === 0 ? <div className="bag-empty"><BagIcon /><h3>Your bag is taking a breather.</h3><p>Find something you’ll reach for every day.</p><button className="button primary" onClick={() => setCartOpen(false)}>Explore the collection</button></div> : <>
              <div className="bag-lines">{cart.map(({ product, quantity }) => <article className="bag-line" key={product.sku}><div className="bag-thumb"><ProductVisual product={product} /></div><div className="bag-line-info"><strong>{product.name}</strong><small>{product.category} · Qty {quantity}</small><button onClick={() => setCart((current) => current.filter((line) => line.product.sku !== product.sku))}>Remove</button></div><b>${(product.price * quantity).toFixed(2)}</b></article>)}</div>
              <div className="bag-summary"><div><span>Subtotal</span><strong>${bagTotal.toFixed(2)}</strong></div><small>Shipping and taxes calculated at checkout.</small><button className="button primary full-width" onClick={beginCheckout}>Continue to checkout <span>→</span></button><p>Demo checkout · No payment collected</p></div>
            </>}
          </aside>
        </div>
      )}
      {checkoutOpen && <CheckoutDialog
        customerName={customerName}
        cart={cart}
        order={checkoutOrder}
        onClose={() => setCheckoutOpen(false)}
        onComplete={(order) => { setCheckoutOrder(order); setCart([]); }}
      />}
      {authDialogOpen && (
        <div className="auth-overlay" onMouseDown={(event) => { if (event.target === event.currentTarget) setAuthDialogOpen(false); }}>
          <button className="auth-close" onClick={() => setAuthDialogOpen(false)} aria-label="Close sign in">×</button>
          <AuthScreen
            mode={authMode}
            setMode={setAuthMode}
            verificationEmail={verificationEmail}
            setVerificationEmail={setVerificationEmail}
            notice={notice}
            error={error}
            clearAlerts={clearAlerts}
            onError={setError}
            onNotice={setNotice}
            onLogin={(name) => {
              setCustomerName(name);
              setAuthenticated(true);
              setActiveSection("shop");
              setAuthDialogOpen(false);
              if (supportPrompt) setChatOpen(true);
            }}
          />
        </div>
      )}
    </main>
  );
}

function BrandMark() {
  return <svg viewBox="0 0 36 36" aria-hidden="true"><path d="M7 27V9h4l7 9 7-9h4v18h-5V17l-6 7-6-7v10z" fill="currentColor"/><circle cx="29" cy="27" r="3" fill="var(--brand-accent)"/></svg>;
}

function CheckoutDialog({
  customerName,
  cart,
  order,
  onClose,
  onComplete,
}: {
  customerName: string;
  cart: CartLine[];
  order: CheckoutOrder | null;
  onClose: () => void;
  onComplete: (order: CheckoutOrder) => void;
}) {
  const [address, setAddress] = useState("");
  const [city, setCity] = useState("");
  const [postalCode, setPostalCode] = useState("");
  const [country, setCountry] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      const result = await apiRequest<CheckoutOrder>("orders/checkout", {
        method: "POST",
        body: JSON.stringify({
          items: cart.map(({ product, quantity }) => ({ sku: product.sku, quantity })),
          shipping_address: [address, city, postalCode, country].filter(Boolean).join(", "),
        }),
      });
      onComplete(result);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create the order. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="checkout-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="checkout-dialog" role="dialog" aria-modal="true" aria-labelledby="checkout-title">
        <div className="checkout-heading"><div><span className="eyebrow">MORROW CHECKOUT</span><h2 id="checkout-title">{order ? "Order received" : "Delivery details"}</h2></div><button onClick={onClose} aria-label="Close checkout">×</button></div>
        {order ? (
          <div className="checkout-success">
            <div className="checkout-success-mark">✓</div>
            <p>Your demo order <strong>{order.order_id}</strong> has been recorded.</p>
            <div className="checkout-order-summary">
              {order.items.map((item) => <div key={item.sku}><span>{item.product_name} × {item.quantity}</span><strong>${(item.price * item.quantity).toFixed(2)}</strong></div>)}
              <div className="checkout-total"><span>Order total</span><strong>${order.total.toFixed(2)}</strong></div>
            </div>
            <div className="checkout-demo-note"><strong>Payment isn’t connected yet.</strong> No charge was made, and this demo order is awaiting payment. Connect a payment provider before accepting real customer purchases.</div>
            <button className="button primary full-width" onClick={onClose}>Continue shopping</button>
          </div>
        ) : (
          <form className="checkout-form" onSubmit={submit}>
            <div className="checkout-summary-line"><span>{cart.reduce((sum, line) => sum + line.quantity, 0)} items</span><strong>${cart.reduce((sum, line) => sum + line.product.price * line.quantity, 0).toFixed(2)}</strong></div>
            <label>Account name<input value={customerName} readOnly /></label>
            <label>Street address<input required minLength={5} maxLength={200} autoComplete="street-address" value={address} onChange={(event) => setAddress(event.target.value)} /></label>
            <div className="checkout-form-row"><label>City<input required maxLength={100} autoComplete="address-level2" value={city} onChange={(event) => setCity(event.target.value)} /></label><label>Postal code<input required maxLength={20} autoComplete="postal-code" value={postalCode} onChange={(event) => setPostalCode(event.target.value)} /></label></div>
            <label>Country<input required maxLength={80} autoComplete="country-name" value={country} onChange={(event) => setCountry(event.target.value)} /></label>
            {error && <div className="notice error">{error}</div>}
            <div className="checkout-demo-note"><strong>Demo checkout.</strong> This creates an unpaid order record. No card is charged and inventory is not reserved.</div>
            <button className="button primary full-width" type="submit" disabled={busy || cart.length === 0}>{busy ? "Checking availability…" : "Create demo order"}<span>→</span></button>
          </form>
        )}
      </section>
    </div>
  );
}

function BagIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 8h14l1 13H4L5 8Z"/><path d="M9 9V6a3 3 0 0 1 6 0v3"/></svg>;
}

function ChatIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11.5a7.5 7.5 0 0 1-7.5 7.5H5l1.3-3A7.5 7.5 0 1 1 20 11.5Z"/><path d="M8.5 12h7M12 8.5v7"/></svg>;
}

function AuthScreen({
  mode,
  setMode,
  verificationEmail,
  setVerificationEmail,
  notice,
  error,
  clearAlerts,
  onError,
  onNotice,
  onLogin,
}: {
  mode: AuthMode;
  setMode: (mode: AuthMode) => void;
  verificationEmail: string;
  setVerificationEmail: (email: string) => void;
  notice: string;
  error: string;
  clearAlerts: () => void;
  onError: (message: string) => void;
  onNotice: (message: string) => void;
  onLogin: (name: string) => void;
}) {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    clearAlerts();
    setBusy(true);
    try {
      if (mode === "login") {
        const session = await apiRequest<{ full_name: string }>("auth/login", {
          method: "POST",
          body: JSON.stringify({ email, password }),
        });
        onLogin(session.full_name);
        return;
      }
      if (mode === "register") {
        await apiRequest("auth/register", {
          method: "POST",
          body: JSON.stringify({ email, full_name: fullName, password }),
        });
        setVerificationEmail(email);
        setMode("verify");
        onNotice("Check your email for a six-digit verification code.");
        return;
      }
      await apiRequest("auth/verify-email", {
        method: "POST",
        body: JSON.stringify({ email: verificationEmail || email, code }),
      });
      setMode("login");
      onNotice("Your email is verified. Sign in to continue.");
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-layout">
      <section className="auth-story">
        <a className="brand light-brand" href="#">
          <span className="brand-mark"><BrandMark /></span>
          <span>morrow<span className="brand-period">.</span></span>
        </a>
        <div className="story-copy">
          <span className="eyebrow light-eyebrow">THOUGHTFULLY CHOSEN TECH</span>
          <h1>Make room<br />for better<br />everydays.</h1>
          <p>Useful things for the desk, the commute, and everywhere in between.</p>
        </div>
        <div className="story-note">Your account keeps your orders and support in one place.</div>
      </section>
      <section className="auth-panel">
        <div className="auth-card">
          <span className="eyebrow">YOUR MORROW ACCOUNT</span>
          <h2>{mode === "login" ? "Welcome back" : mode === "register" ? "Create your account" : "Verify your email"}</h2>
          <p className="muted">
            {mode === "login"
              ? "Sign in to see your orders and get help tailored to you."
              : mode === "register"
                ? "Join us to keep your shopping organized."
                : "Enter the verification code we sent you."}
          </p>
          {notice && <div className="notice success">{notice}</div>}
          {error && <div className="notice error">{error}</div>}
          <form onSubmit={submit} className="form-stack">
            {mode === "register" && (
              <label>
                Full name
                <input required value={fullName} onChange={(event) => setFullName(event.target.value)} autoComplete="name" />
              </label>
            )}
            {mode !== "verify" && (
              <label>
                Email address
                <input
                  required
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  autoComplete="email"
                />
              </label>
            )}
            {mode === "verify" && (
              <>
                <label>
                  Email address
                  <input required type="email" value={verificationEmail || email} onChange={(event) => setVerificationEmail(event.target.value)} />
                </label>
                <label>
                  Six-digit code
                  <input required inputMode="numeric" pattern="[0-9]{6}" maxLength={6} value={code} onChange={(event) => setCode(event.target.value)} />
                </label>
              </>
            )}
            {mode !== "verify" && (
              <label>
                Password
                <input
                  required
                  type="password"
                  minLength={mode === "register" ? 10 : 1}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                />
                {mode === "register" && <small>Use at least 10 characters.</small>}
              </label>
            )}
            <button className="button primary full-width" disabled={busy}>
              {busy ? "Please wait…" : mode === "login" ? "Sign in" : mode === "register" ? "Create account" : "Verify email"}
            </button>
          </form>
          <div className="auth-switch">
            {mode === "login" ? (
              <>New here? <button onClick={() => { clearAlerts(); setMode("register"); }}>Create an account</button></>
            ) : (
              <>Already have an account? <button onClick={() => { clearAlerts(); setMode("login"); }}>Sign in</button></>
            )}
          </div>
          {mode !== "verify" && (
            <button className="subtle-link" onClick={() => { clearAlerts(); setMode("verify"); }}>
              Need to verify your email?
            </button>
          )}
        </div>
      </section>
    </main>
  );
}

function ShopSection({
  onError,
  onClearError,
  onOpenSupport,
  onAddToBag,
}: {
  onError: (message: string) => void;
  onClearError: () => void;
  onOpenSupport: (prompt: string) => void;
  onAddToBag: (product: Product) => void;
}) {
  const [products, setProducts] = useState<Product[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [inStock, setInStock] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiRequest<{ categories: string[] }>("products/categories")
      .then((result) => setCategories(result.categories))
      .catch((reason: unknown) =>
        onError(reason instanceof Error ? reason.message : "Could not load categories."),
      );
  }, [onError]);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true);
      onClearError();
      const params = new URLSearchParams();
      if (query.trim()) params.set("query", query.trim());
      if (category) params.set("category", category);
      if (inStock) params.set("in_stock", "true");
      apiRequest<Product[]>(`products?${params.toString()}`, {
        signal: controller.signal,
      })
        .then(setProducts)
        .catch((reason: unknown) => {
          if (reason instanceof DOMException && reason.name === "AbortError") return;
          onError(reason instanceof Error ? reason.message : "Could not load products.");
        })
        .finally(() => setLoading(false));
    }, 180);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query, category, inStock, onError, onClearError]);

  return (
    <>
      <section className="hero">
        <div>
          <span className="eyebrow">TECH FOR YOUR EVERYDAY</span>
          <h1>Make space for<br /><span>better ideas.</span></h1>
          <p>Thoughtful tech essentials for focused work, easy connections, and more comfortable days.</p>
          <a className="button dark-button" href="#catalog">Browse all products <span>↓</span></a>
        </div>
        <div className="hero-art" aria-label="Everyday tech essentials">
          <img src="https://images.unsplash.com/photo-1496181133206-80ce9b88a853?auto=format&fit=crop&w=1100&q=85" alt="Laptop and workspace in warm morning light" />
          <div className="hero-photo-caption">A little more room<br />for good ideas.</div>
        </div>
      </section>

      <section className="benefit-strip" aria-label="Shopping benefits">
        <div><span>01</span><strong>Good things, chosen well</strong><small>Everyday tech that earns its place.</small></div>
        <div><span>02</span><strong>Thoughtful support</strong><small>Help with products, orders, and delivery.</small></div>
        <div><span>03</span><strong>14-day return window</strong><small>Unused items in original packaging.</small></div>
      </section>

      <section className="collection-section" id="catalog">
        <div className="section-heading">
          <div>
            <span className="eyebrow">THE EVERYDAY TECH EDIT</span>
            <h2>Find your next favorite</h2>
          </div>
          <span className="muted">{products.length} products</span>
        </div>
        <div className="catalog-controls">
          <label className="search-field">
            <span aria-hidden="true">⌕</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search products…"
              aria-label="Search products"
            />
          </label>
          <select value={category} onChange={(event) => setCategory(event.target.value)} aria-label="Filter by category">
            <option value="">All categories</option>
            {categories.map((item) => <option value={item} key={item}>{item}</option>)}
          </select>
          <label className="stock-filter">
            <input type="checkbox" checked={inStock} onChange={(event) => setInStock(event.target.checked)} />
            In stock only
          </label>
        </div>
        {loading ? (
          <div className="empty-state">Finding your favorites…</div>
        ) : products.length === 0 ? (
          <div className="empty-state">No products match those filters. Try a different search.</div>
        ) : (
          <div className="product-grid">
            {products.map((product, index) => (
              <article className="product-card" key={product.sku}>
                <div className={`product-art art-${index % 6}`}>
                  <span className="product-category">{product.category}</span>
                  <ProductVisual product={product} loading={index > 3 ? "lazy" : "eager"} />
                  {product.inventory > 0 && <span className="product-stock-pill">In stock</span>}
                </div>
                <div className="product-info">
                  <div className="product-title-row">
                    <h3>{product.name}</h3>
                    <span className="price">${product.price.toFixed(2)}</span>
                  </div>
                  <p>{product.description}</p>
                  <div className="product-availability">
                    <span className={product.inventory ? "status-dot available" : "status-dot unavailable"} />
                    {product.inventory ? `${product.inventory} in stock` : "Currently unavailable"}
                  </div>
                  <div className="product-actions">
                    <button className="add-to-bag" disabled={!product.inventory} onClick={() => onAddToBag(product)}>{product.inventory ? "Add to bag" : "Sold out"}<span aria-hidden="true">＋</span></button>
                    <button className="product-help-link" aria-label={`Ask about ${product.name}`} onClick={() => onOpenSupport(`Is the ${product.name} in stock, and what are its key details?`)}><ChatIcon /></button>
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
      <section className="brand-story"><span className="eyebrow">A NOTE FROM MORROW</span><h2>Useful things.<br /><em>Better everyday.</em></h2><p>We believe the things you use every day should feel thoughtful, work beautifully, and last longer than the unboxing.</p><button onClick={() => onOpenSupport("Tell me more about Morrow and your product recommendations.")}>Get a recommendation <span>→</span></button></section>
    </>
  );
}

function productImage(name: string) {
  const item = name.toLowerCase();
  if (item.includes("headphone")) return "https://images.unsplash.com/photo-1599955051125-571f47e04316?auto=format&fit=crop&w=800&q=80";
  if (item.includes("keyboard")) return "https://images.unsplash.com/photo-1771370596565-683a5a952de2?auto=format&fit=crop&w=800&q=80";
  if (item.includes("mouse") && !item.includes("pad")) return "https://images.unsplash.com/photo-1707592691247-5c3a1c7ba0e3?auto=format&fit=crop&w=800&q=80";
  if (item.includes("monitor")) return "https://images.unsplash.com/photo-1527443224154-c4a3942d3acf?auto=format&fit=crop&w=800&q=80";
  if (item.includes("speaker")) return "https://images.unsplash.com/photo-1589003077984-894e133dabab?auto=format&fit=crop&w=800&q=80";
  if (item.includes("watch")) return "https://images.unsplash.com/photo-1523275335684-37898b6baf30?auto=format&fit=crop&w=800&q=80";
  if (item.includes("ssd")) return "https://images.unsplash.com/photo-1577538926210-fc6cc624fde2?auto=format&fit=crop&w=800&q=80";
  return "";
}

function ProductVisual({ product, loading = "lazy" }: { product: Product; loading?: "eager" | "lazy" }) {
  const image = productImage(product.name);
  const [failed, setFailed] = useState(false);
  if (!image || failed) return <div className="product-visual-fallback"><ProductIllustration name={product.name} /></div>;
  return <img src={image} alt={product.name} loading={loading} onError={() => setFailed(true)} />;
}

function ProductIllustration({ name }: { name: string }) {
  const item = name.toLowerCase();
  let object: React.ReactNode;
  if (item.includes("headphone")) object = <><path d="M24 45v-8a26 26 0 0 1 52 0v8"/><rect x="20" y="42" width="13" height="23" rx="6"/><rect x="67" y="42" width="13" height="23" rx="6"/><path d="M33 66c8 6 19 7 28 2"/></>;
  else if (item.includes("keyboard")) object = <><rect x="12" y="25" width="76" height="42" rx="7"/><path d="M20 35h4m8 0h4m8 0h4m8 0h4m8 0h4m8 0h4M20 45h4m8 0h4m8 0h4m8 0h4m8 0h4m8 0h4M21 56h10m7 0h32m6 0h4"/></>;
  else if (item.includes("monitor")) object = <><rect x="15" y="16" width="70" height="46" rx="5"/><path d="M50 62v12m-16 0h32"/><circle cx="50" cy="54" r="1"/></>;
  else if (item.includes("mouse")) object = <><path d="M50 16c-14 0-23 10-23 25v15c0 14 9 23 23 23s23-9 23-23V41c0-15-9-25-23-25Z"/><path d="M50 17v22m-1 0h2"/></>;
  else if (item.includes("mousepad")) object = <><rect x="12" y="32" width="76" height="37" rx="9"/><path d="M59 18c-9 0-14 7-14 16v13c0 8 5 13 13 13s13-5 13-13V34c0-9-4-16-12-16Z"/><path d="M58 19v13"/></>;
  else if (item.includes("charger")) object = <><circle cx="50" cy="48" r="25"/><circle cx="50" cy="48" r="16"/><path d="m52 36-9 14h9l-4 11 11-16h-9l2-9Z"/></>;
  else if (item.includes("tablet stand")) object = <><rect x="35" y="13" width="31" height="43" rx="4" transform="rotate(-8 35 13)"/><path d="m43 56 16 16m-28 2h43"/></>;
  else if (item.includes("protector")) object = <><rect x="28" y="12" width="44" height="65" rx="7"/><path d="M38 21h24m-22 47h20"/><path d="m71 24 8-8m-9 20 11-3"/></>;
  else if (item.includes("ssd")) object = <><rect x="25" y="16" width="50" height="63" rx="8"/><path d="M39 27h22m-22 8h22M50 62v8m-8-4h16"/><circle cx="50" cy="49" r="6"/></>;
  else if (item.includes("watch")) object = <><path d="m39 23 4-12h14l4 12m-22 43 4 12h14l4-12"/><rect x="31" y="22" width="38" height="45" rx="11"/><circle cx="50" cy="42" r="8"/><path d="M50 34v8l6 4"/></>;
  else if (item.includes("speaker")) object = <><rect x="32" y="13" width="36" height="66" rx="15"/><circle cx="50" cy="37" r="10"/><circle cx="50" cy="61" r="5"/></>;
  else object = <><path d="M35 18h30l8 54H27l8-54Z"/><path d="M42 24h16m-20 36h24"/><path d="M73 27h8v14h-8"/></>;
  return <svg className="product-illustration" viewBox="0 0 100 90" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{object}</svg>;
}

function OrdersSection({
  onError,
  onClearError,
}: {
  onError: (message: string) => void;
  onClearError: () => void;
}) {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    onClearError();
    apiRequest<Order[]>("orders/mine")
      .then((result) => { if (active) setOrders(result); })
      .catch((reason: unknown) => {
        if (active) onError(reason instanceof Error ? reason.message : "Could not load your orders.");
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [onError, onClearError]);

  return (
    <section className="content-card">
      <div className="section-heading">
        <div><span className="eyebrow">YOUR SHOPPING</span><h1>My orders</h1></div>
        <span className="muted">{orders.length} total</span>
      </div>
      {loading ? <div className="empty-state">Loading your orders…</div> : orders.length === 0 ? (
        <div className="empty-state"><span className="empty-icon">□</span><h3>Your next favorite is out there.</h3><p>Your orders will show up here after checkout.</p></div>
      ) : (
        <div className="orders-list">
          {orders.map((order) => (
            <article className="order-card" key={order.order_id}>
              <div className="order-heading">
                <div><span className="eyebrow">ORDER PLACED</span><p>{new Date(order.created_at).toLocaleDateString()}</p></div>
                <div><span className="eyebrow">ORDER NUMBER</span><p>{order.order_id}</p></div>
                <div><span className={`order-status status-${order.status}`}>{order.status.replaceAll("_", " ")}</span></div>
                <strong>${order.total.toFixed(2)}</strong>
              </div>
              <div className="order-items">
                {order.items.map((item) => (
                  <div className="order-item" key={`${order.order_id}-${item.sku}`}>
                    <span className="item-mark">✳</span>
                    <div><strong>{item.product_name}</strong><small>{item.sku} · Qty {item.quantity}</small></div>
                    <span>${item.price.toFixed(2)}</span>
                  </div>
                ))}
              </div>
              {order.tracking_number && <div className="tracking-line">Tracking number <strong>{order.tracking_number}</strong></div>}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function SupportSection({
  authenticated,
  initialPrompt,
  onError,
  onClearError,
  onClose,
}: {
  authenticated: boolean;
  initialPrompt: string;
  onError: (message: string) => void;
  onClearError: () => void;
  onClose: () => void;
}) {
  const greeting = "Hi, I’m Morrow’s shopping assistant. I can help you find the right product or answer a store policy question. What are you looking for?";
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: "assistant", content: greeting },
  ]);
  const [input, setInput] = useState(initialPrompt);
  const [busy, setBusy] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(authenticated);
  const [confirmingCancellation, setConfirmingCancellation] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (initialPrompt) setInput(initialPrompt);
  }, [initialPrompt]);

  useEffect(() => {
    if (!authenticated) {
      setHistoryLoading(false);
      return;
    }
    let active = true;
    void apiRequest<{
      messages: Array<ChatMessage & {
        pending_cancellation_id?: string;
        pending_cancellation_order_id?: string;
      }>;
    }>("chat/history?session_id=default")
      .then((history) => {
        if (active && history.messages.length) {
          setMessages(history.messages.map((message) => {
            return {
              ...message,
              pendingCancellation: message.pending_cancellation_id && message.pending_cancellation_order_id
                ? {
                    cancellation_id: message.pending_cancellation_id,
                    order_id: message.pending_cancellation_order_id,
                  }
                : parsePendingCancellation(message.content),
            };
          }));
        }
      })
      .catch((reason: unknown) => {
        if (active) onError(
          reason instanceof Error ? reason.message : "Could not load conversation history.",
        );
      })
      .finally(() => { if (active) setHistoryLoading(false); });
    return () => { active = false; };
  }, [authenticated, onError]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy]);

  const quickActions = useMemo(() => [
    { icon: "01", title: "Find a product", detail: "Search the live catalog", prompt: "Help me find a useful desk accessory." },
    { icon: "02", title: "Recommendations", detail: "Get help choosing", prompt: "What would you recommend for a home office?" },
    { icon: "03", title: "Returns", detail: "Read the store policy", prompt: "What is your return window?" },
    { icon: "04", title: "My order", detail: "Sign in for personal help", prompt: "Can you check my recent orders?" },
  ], []);

  const confirmedCancellationIds = useMemo(() => new Set(
    messages
      .map((message) => message.content.match(/Cancellation confirmed for order \*\*[A-Z0-9-]+\*\*\. Request `?(CAN-[A-Z0-9-]+)`? is complete/i)?.[1])
      .filter((requestId): requestId is string => Boolean(requestId)),
  ), [messages]);

  async function confirmCancellation(cancellationId: string, orderId: string) {
    if (busy || confirmingCancellation) return;
    onClearError();
    setConfirmingCancellation(cancellationId);
    try {
      const result = await apiRequest<{
        cancellation_id: string;
        order_id: string;
        status: string;
        message: string;
      }>(`cancellation-requests/${encodeURIComponent(cancellationId)}/confirm?session_id=default`, {
        method: "POST",
      });
      setMessages((current) => [
        ...current,
        { role: "user", content: `Confirm cancellation request ${cancellationId}.` },
        { role: "assistant", content: result.message || `Cancellation confirmed for order **${orderId}**.` },
      ]);
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Could not confirm the cancellation.");
    } finally {
      setConfirmingCancellation("");
    }
  }

  async function sendMessage(text: string) {
    const message = text.trim();
    if (!message || busy || historyLoading) return;
    onClearError();
    setInput("");
    setMessages((current) => [...current, { role: "user", content: message }]);
    setBusy(true);
    try {
      const history = messages
        .filter((item) => item.role === "user" || item.role === "assistant")
        .slice(-12)
        .map(({ role, content }) => ({ role, content }));
      const result = await apiRequest<{
        response: string;
        pending_cancellation_id?: string;
        pending_cancellation_order_id?: string;
      }>(authenticated ? "chat" : "chat/guest", {
        method: "POST",
        body: JSON.stringify(authenticated
          ? { message, session_id: "default" }
          : { message, history }),
      });
      const pendingCancellation = result.pending_cancellation_id && result.pending_cancellation_order_id
        ? { cancellation_id: result.pending_cancellation_id, order_id: result.pending_cancellation_order_id }
        : parsePendingCancellation(result.response);
      setMessages((current) => [...current, {
        role: "assistant",
        content: result.response,
        pendingCancellation,
      }]);
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Could not send your message.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="support-page">
      <div className="support-intro">
        <div><span className="eyebrow">SHOPASSIST CARE</span><h1>How can we help?</h1><p>Get a quick answer or choose a topic to get started.</p></div>
        <div className="support-promise"><span className="promise-mark">✳</span><span><strong>Here for your order</strong><small>Personalized help, backed by your account</small></span></div>
      </div>
      <div className="support-layout">
        <div className="chat-panel">
          <div className="chat-header">
            <span className="support-icon small">✳</span>
            <div><strong>Morrow support</strong><small>Products, store policies, and account help</small></div>
            <button className="text-button clear-chat" disabled={busy || historyLoading} onClick={() => {
              if (!authenticated) {
                setMessages([{ role: "assistant", content: greeting }]);
                setInput("");
                return;
              }
              void apiRequest<{ deleted_messages: number }>("chat/history?session_id=default", { method: "DELETE" })
                .then(() => setMessages([{ role: "assistant", content: greeting }]))
                .catch((reason: unknown) => onError(reason instanceof Error ? reason.message : "Could not clear history."));
            }}>{authenticated ? "New chat" : "Clear"}</button>
            <button className="chat-close-button" onClick={onClose} aria-label="Close support chat">×</button>
          </div>
          <div className="chat-messages">
            {historyLoading && <p className="chat-loading">Loading your conversation…</p>}
            {messages.map((message, index) => {
              const pending = message.pendingCancellation;
              return (
                <div className={`chat-message ${message.role}`} key={`${index}-${message.role}`}>
                  {message.role === "assistant" && <span className="chat-avatar">S</span>}
                  <div className="message-bubble">
                    {renderMessageContent(message.content)}
                    {pending && !confirmedCancellationIds.has(pending.cancellation_id) && (
                      <div className="cancellation-confirmation">
                        <strong>Confirm this cancellation?</strong>
                        <span>Order {pending.order_id} will be cancelled when you confirm.</span>
                        <button
                          type="button"
                          className="button dark-button"
                          disabled={busy || Boolean(confirmingCancellation)}
                          onClick={() => void confirmCancellation(pending.cancellation_id, pending.order_id)}
                        >
                          {confirmingCancellation === pending.cancellation_id ? "Confirming…" : "Confirm cancellation"}
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
            {busy && <div className="typing-indicator"><span /><span /><span /> Morrow is thinking…</div>}
            <div ref={messagesEndRef} />
          </div>
          <form className="chat-composer" onSubmit={(event) => { event.preventDefault(); void sendMessage(input); }}>
            <textarea
              value={input}
              onChange={(event) => {
                setInput(event.target.value);
                event.currentTarget.style.height = "auto";
                event.currentTarget.style.height = `${Math.min(event.currentTarget.scrollHeight, 120)}px`;
              }}
              onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void sendMessage(input); } }}
              placeholder="Ask a question or describe what happened…"
              aria-label="Write your support message"
              rows={1}
              disabled={historyLoading}
            />
            <button className="send-button" disabled={busy || historyLoading || !input.trim()} aria-label="Send message">↑</button>
          </form>
          <div className="composer-footer"><span>Enter to send <b>·</b> Shift + Enter for a new line</span><span>AI can make mistakes. Confirm important order details.</span></div>
        </div>
        <aside className="quick-help">
          <div className="quick-help-heading"><span className="eyebrow">QUICK HELP</span><h2>Start with a topic</h2><p>Choose a shortcut or type your own question.</p></div>
          <div className="quick-help-list">
            {quickActions.map((action) => (
              <button
                className="quick-help-action"
                key={action.title}
                disabled={busy || historyLoading}
                onClick={() => void sendMessage(action.prompt)}
              >
                <span className="quick-help-icon">{action.icon}</span>
                <span className="quick-help-copy"><strong>{action.title}</strong><small>{action.detail}</small></span>
                <span className="quick-help-arrow" aria-hidden="true">↗</span>
              </button>
            ))}
          </div>
          <div className="help-note"><span>i</span><p>Order answers use the account you’re signed in with. Use the order number from <strong>My orders</strong>.</p></div>
        </aside>
      </div>
    </section>
  );
}

function renderMessageContent(content: string) {
  return content.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code className="message-code" key={index}>{part.slice(1, -1)}</code>;
    }
    return <span key={index}>{part}</span>;
  });
}

function parsePendingCancellation(content: string) {
  const cancellationId = content.match(/Request reference:\s*`?(CAN-[A-Z0-9-]+)`?/i)?.[1];
  const orderId = content.match(/cancellation request for\s+\*{0,2}(ORD-[A-Z0-9-]+)\*{0,2}/i)?.[1];
  return cancellationId && orderId
    ? { cancellation_id: cancellationId.toUpperCase(), order_id: orderId.toUpperCase() }
    : undefined;
}

function AccountSection({
  onError,
  onClearError,
  onOpenOrders,
  onOpenSupport,
}: {
  onError: (message: string) => void;
  onClearError: () => void;
  onOpenOrders: () => void;
  onOpenSupport: () => void;
}) {
  const [profile, setProfile] = useState<{ full_name: string; email: string } | null>(null);

  useEffect(() => {
    let active = true;
    onClearError();
    apiRequest<{ full_name: string; email: string }>("auth/me")
      .then((result) => { if (active) setProfile(result); })
      .catch((reason: unknown) => {
        if (active) onError(reason instanceof Error ? reason.message : "Could not load your account.");
      });
    return () => { active = false; };
  }, [onError, onClearError]);

  return (
    <section className="content-card account-card">
      <span className="eyebrow">YOUR DETAILS</span>
      <h1>Account</h1>
      <p className="muted">Your account details and shopping activity, together in one place.</p>
      {profile ? (
        <div className="profile-details">
          <div className="profile-avatar">{profile.full_name.slice(0, 1).toUpperCase()}</div>
          <div><small>FULL NAME</small><strong>{profile.full_name}</strong></div>
          <div><small>EMAIL ADDRESS</small><strong>{profile.email}</strong></div>
          <div><small>ACCOUNT STATUS</small><strong className="verified-label">✓ Verified</strong></div>
        </div>
      ) : <div className="empty-state">Loading account details…</div>}
      <div className="account-security"><span>♢</span><div><strong>Your account is protected</strong><p>Your orders and support conversations are available while you’re signed in.</p></div></div>
      <div className="account-shortcuts">
        <button onClick={onOpenOrders}><span>ORDER HISTORY</span><strong>View your orders <b aria-hidden="true">↗</b></strong></button>
        <button onClick={onOpenSupport}><span>NEED A HAND?</span><strong>Talk to Morrow <b aria-hidden="true">↗</b></strong></button>
      </div>
    </section>
  );
}
