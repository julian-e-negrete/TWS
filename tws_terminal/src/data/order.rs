#[derive(Clone, Debug)]
pub struct Order {
    pub id: u32,
    pub exchange: String,
    pub side: String,
    pub price: f64,
    pub quantity: u32,
    pub status: String,
}

impl Order {
    pub fn new(side: String, price: f64, quantity: u32, exchange: String) -> Self {
        static mut NEXT_ID: u32 = 1;
        
        let id = unsafe {
            let current = NEXT_ID;
            NEXT_ID += 1;
            current
        };
        
        Self {
            id,
            exchange,
            side,
            price,
            quantity,
            status: "OPEN".to_string(),
        }
    }
}